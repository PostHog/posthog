import json
from datetime import datetime
from enum import Enum

from django.core.cache import cache

from posthog.constants import CachedEndpoint
from posthog.models import DashboardItem, Filter
from posthog.utils import generate_cache_key

from .utils import generate_cache_key


def cached_function(cache_type: CachedEndpoint, expiry=30):
    def inner_decorator(f):
        def wrapper(*args, **kw):
            from posthog.celery import update_cache_item_task

            cache_key = ""

            # prepare caching params
            request = args[1]
            team = request.user.team_set.get()
            payload = None
            refresh = request.GET.get("refresh", None)

            if cache_type == CachedEndpoint.TRENDS:
                filter = Filter(request=request)
                cache_key = generate_cache_key(filter.toJSON() + "_" + str(team.pk))
                payload = {"filter": filter.toJSON(), "team_id": team.pk}
            elif cache_type == CachedEndpoint.FUNNEL_VIZ:
                pk = args[2]
                cache_key = generate_cache_key("funnel_{}_{}".format(pk, team.pk))
                payload = {"funnel_id": pk, "team_id": team.pk}

            if not refresh:
                # return result if cached
                cached_result = cache.get(cache_key)
                if cached_result:
                    return cached_result["result"]

            # call wrapped function
            result = f(*args, **kw)

            # cache new data using
            if result and payload:
                cache.set(
                    cache_key, {"result": result, "details": payload, "type": cache_type,}, expiry,
                )

            return result

        return wrapper

    return inner_decorator
