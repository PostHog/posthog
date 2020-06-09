import json
import hashlib
from posthog.models import Filter
from django.core.cache import cache

def generate_cache_key(obj):
    stringified = json.dumps(obj)
    return hashlib.md5(stringified.encode("utf-8")).hexdigest()


TRENDS_ENDPOINT = 'Trends'
FUNNEL_STEPS = 'Funnel_Steps'

def cached_function(cache_type: str):
    def inner_decorator(f):
        def wrapper(*args, **kw):
            cache_key = ''

            if cache_type == TRENDS_ENDPOINT:
                request = args[1]
                filter = Filter(request=request)
                cache_key = generate_cache_key(filter.toJSON())
            elif cache_type == FUNNEL_STEPS:
                funnel = args[0]
                filter = Filter(data=funnel.filters)
                cache_key = generate_cache_key(filter.toJSON())

            cached_result = cache.get(cache_key + '_' + cache_type)

            if cached_result is not None:
                return cached_result

            result = f(*args, **kw)

            if result is not None:
                cache.set(cache_key, result, 60)
                
            return result
        return wrapper
    return inner_decorator