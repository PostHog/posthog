import json
import hashlib
from posthog.models import Filter
from django.core.cache import cache

def generate_cache_key(obj):
    stringified = json.dumps(obj)
    return hashlib.md5(stringified.encode("utf-8")).hexdigest()


TRENDS_ENDPOINT = 'Trends'
FUNNEL_STEPS = 'Funnel_Steps'

def cached_function(cache_type: str, expiry=60):
    def inner_decorator(f):
        def wrapper(*args, **kw):
            cache_key = ''
            _expiry = expiry
            filter = None
            params = None
            team = None
            if cache_type == TRENDS_ENDPOINT:
                filter =  args[1]
                params = args[2]
                team = args[3]
                cache_key = generate_cache_key(filter.toJSON())
                if params.get('dashboard'): #cache for 30 minutes if dashboard item
                    _expiry = 1800
            elif cache_type == FUNNEL_STEPS:
                funnel = args[0]
                filter = Filter(data=funnel.filters)
                cache_key = generate_cache_key(filter.toJSON())

            cache_key = cache_key + '_' + cache_type

            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result['result']

            result = f(*args, **kw)

            if result is not None:
                cache.set(cache_key, {'result':result, 'details': {'filter': filter, 'params': params, 'team': team}}, _expiry)

            return result
        return wrapper
    return inner_decorator