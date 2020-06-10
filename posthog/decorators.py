import json
import hashlib
from posthog.models import Filter
from django.core.cache import cache

def generate_cache_key(obj):
    stringified = json.dumps(obj)
    return hashlib.md5(stringified.encode("utf-8")).hexdigest()


TRENDS_ENDPOINT = 'Trends'
FUNNEL_ENDPOINT = 'Funnel'

def cached_function(cache_type: str, expiry=30):
    def inner_decorator(f):
        def wrapper(*args, **kw):
            cache_key = ''
            _expiry = expiry

            # prepare caching params
            filter = None
            params = None
            team = None
            payload = None

            if cache_type == TRENDS_ENDPOINT:
                request = args[1]
                filter =  Filter(request=request)
                params = request.GET.dict()
                team = request.user.team_set.get()
                cache_key = generate_cache_key(filter.toJSON())
                payload = {'filter': filter, 'params': params, 'team': team}
            elif cache_type == FUNNEL_ENDPOINT:
                request = args[1]
                pk = args[2]
                params = request.GET.dict()
                team = request.user.team_set.get()
                cache_key = generate_cache_key(str(pk) + '_' + str(team.pk))
                payload = {'pk': pk, 'params': params, 'team': team}
            
            if params.get('refresh'):
                cache.delete(cache_key + '_' + cache_type)
                cache.delete(cache_key + '_' + 'dashboard' + '_' + cache_type)

            if params.get('from_dashboard'): #cache for 30 minutes if dashboard item
                cache_key = cache_key + '_' + 'dashboard'
                _expiry = 1800

            cache_key = cache_key + '_' + cache_type

            # return result if cached
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result['result']

            # call wrapped function
            result = f(*args, **kw)

            # cache new data using
            if result is not None and payload is not None:
                cache.set(cache_key, {'result':result, 'details': payload, 'type': cache_type}, _expiry)

            return result
        return wrapper
    return inner_decorator