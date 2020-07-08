import json
import hashlib
from posthog.models import Filter, DashboardItem
from django.core.cache import cache
import json
from posthog.celery import update_cache_item
from datetime import datetime


def generate_cache_key(obj):
    stringified = json.dumps(obj)
    return hashlib.md5(stringified.encode("utf-8")).hexdigest()


TRENDS_ENDPOINT = "Trends"
FUNNEL_ENDPOINT = "Funnel"


def cached_function(cache_type: str, expiry=30):
    def inner_decorator(f):
        def wrapper(*args, **kw):
            cache_key = ""
            _expiry = expiry

            # prepare caching params
            filter = None
            params = None
            team = None
            payload = None
            refresh = False
            dashboard_item_id = None

            if cache_type == TRENDS_ENDPOINT:
                request = args[1]
                filter = Filter(request=request)
                params = request.GET.dict()
                refresh = params.pop("refresh", None)
                team = request.user.team_set.get()
                cache_key = generate_cache_key(json.dumps(params) + "_" + str(team.pk))
                payload = {
                    "filter": filter.toJSON(),
                    "params": params,
                    "team_id": team.pk,
                }
            elif cache_type == FUNNEL_ENDPOINT:
                request = args[1]
                pk = args[2]
                params = request.GET.dict()
                refresh = params.pop("refresh", None)
                team = request.user.team_set.get()
                cache_key = generate_cache_key(str(pk) + "_" + str(team.pk))
                payload = {"pk": pk, "params": params, "team_id": team.pk}

            if params and payload and params.get("from_dashboard"):  # cache for 30 minutes if dashboard item
                cache_key = cache_key + "_" + "dashboard"
                _expiry = 900
                dashboard_item_id = params.get("from_dashboard")
                payload.update({"dashboard_id": dashboard_item_id})

            cache_key = cache_key + "_" + cache_type

            if refresh and dashboard_item_id:
                dashboard_item = DashboardItem.objects.filter(pk=dashboard_item_id)
                dashboard_item.update(refreshing=True)
                update_cache_item.delay(cache_key, cache_type, payload, datetime.now())
            elif refresh:
                cache.delete(cache_key)

            # return result if cached
            cached_result = cache.get(cache_key)
            if cached_result:
                return cached_result["result"]

            # call wrapped function
            result = f(*args, **kw)

            # cache new data using
            if result and payload:
                cache.set(
                    cache_key,
                    {"result": result, "details": payload, "type": cache_type, "last_accessed": datetime.now(),},
                    _expiry,
                )

            return result

        return wrapper

    return inner_decorator
