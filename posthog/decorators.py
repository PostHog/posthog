import json
import hashlib
from posthog.models import Filter
from django.core.cache import cache
import json

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
            refresh = False

            if cache_type == TRENDS_ENDPOINT:
                request = args[1]
                filter =  Filter(request=request)
                params = request.GET.dict()
                refresh = params.pop('refresh', None)
                team = request.user.team_set.get()
                cache_key = generate_cache_key(json.dumps(params) + '_' + str(team.pk))
                payload = {'filter': filter.toJSON(), 'params': params, 'team_id': team.pk}
            elif cache_type == FUNNEL_ENDPOINT:
                request = args[1]
                pk = args[2]
                params = request.GET.dict()
                refresh = params.pop('refresh', None)
                team = request.user.team_set.get()
                cache_key = generate_cache_key(str(pk) + '_' + str(team.pk))
                payload = {'pk': pk, 'params': params, 'team_id': team.pk}
            
            if params and refresh:
                cache.delete(cache_key + '_' + cache_type)
                cache.delete(cache_key + '_' + 'dashboard' + '_' + cache_type)

            if params and payload and params.get('from_dashboard'): #cache for 30 minutes if dashboard item
                cache_key = cache_key + '_' + 'dashboard'
                _expiry = 900
                dashboard_id = params.get('from_dashboard')
                payload.update({'dashboard_id': dashboard_id})
                

            cache_key = cache_key + '_' + cache_type

            # return result if cached
            cached_result = cache.get(cache_key)
            if cached_result :
                return cached_result['result']

            # call wrapped function
            result = f(*args, **kw)

            # cache new data using
            if result and payload:
                cache.set(cache_key, {'result':result, 'details': payload, 'type': cache_type}, _expiry)

            return result
        return wrapper
    return inner_decorator