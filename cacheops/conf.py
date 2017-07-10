# -*- coding: utf-8 -*-
from copy import deepcopy
import warnings
import redis
from funcy import memoize, decorator, identity

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured



profile_defaults = {
    'ops': (),
    'local_get': False,
    'db_agnostic': True,
}
profiles = {
    'just_enable': {},
    'all': {'ops': ('get', 'fetch', 'count')},
    'get': {'ops': ('get',)},
    'count': {'ops': ('count',)},
}
for key in profiles:
    profiles[key] = dict(profile_defaults, **profiles[key])


STRICT_STRINGIFY = getattr(settings, 'CACHEOPS_STRICT_STRINGIFY', False)
DEGRADE_ON_FAILURE = getattr(settings, 'CACHEOPS_DEGRADE_ON_FAILURE', False)


# Support DEGRADE_ON_FAILURE
if DEGRADE_ON_FAILURE:
    @decorator
    def handle_connection_failure(call):
        try:
            return call()
        except redis.ConnectionError as e:
            warnings.warn("The cacheops cache is unreachable! Error: %s" % e, RuntimeWarning)
else:
    handle_connection_failure = identity

class SafeRedis(redis.StrictRedis):
    get = handle_connection_failure(redis.StrictRedis.get)


# Connecting to redis
try:
    redis_conf = settings.CACHEOPS_REDIS
except AttributeError:
    raise ImproperlyConfigured('You must specify non-empty CACHEOPS_REDIS setting to use cacheops')

redis_client = (SafeRedis if DEGRADE_ON_FAILURE else redis.StrictRedis)(**redis_conf)


@memoize
def prepare_profiles():
    """
    Prepares a dict 'app.model' -> profile, for use in model_profile()
    """
    if hasattr(settings, 'CACHEOPS_PROFILES'):
        profiles.update(settings.CACHEOPS_PROFILES)

    model_profiles = {}
    ops = getattr(settings, 'CACHEOPS', {})
    for app_model, profile in ops.items():
        profile_name, timeout = profile[:2]

        try:
            model_profiles[app_model] = mp = deepcopy(profiles[profile_name])
        except KeyError:
            raise ImproperlyConfigured('Unknown cacheops profile "%s"' % profile_name)

        if len(profile) > 2:
            mp.update(profile[2])
        mp['timeout'] = timeout
        mp['ops'] = set(mp['ops'])

    return model_profiles

@memoize
def model_profile(model):
    """
    Returns cacheops profile for a model
    """
    model_profiles = prepare_profiles()

    app = model._meta.app_label
    # module_name is fallback for Django 1.5-
    model_name = getattr(model._meta, 'model_name', None) or model._meta.module_name
    app_model = '%s.%s' % (app, model_name)
    for guess in (app_model, '%s.*' % app, '*.*'):
        if guess in model_profiles:
            return model_profiles[guess]
    else:
        return None