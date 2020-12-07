from enum import Enum
from functools import wraps
from typing import Callable, cast

from django.conf import settings
from django.core.cache import cache
from django.http.request import HttpRequest
from django.utils.timezone import now

from posthog.ee import is_ee_enabled
from posthog.models import Filter, Team, User
from posthog.models.dashboard_item import DashboardItem
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.settings import CACHED_RESULTS_TTL
from posthog.utils import generate_cache_key

from .utils import generate_cache_key


class CacheType(str, Enum):
    FILTER = "Filter"
    TRENDS = "Trends"
    RETENTION = "Retention"
    STICKINESS = "Stickiness"
    PATHS = "Path"
    FUNNEL = "Funnel"


TYPE_TO_FILTER = {
    CacheType.TRENDS: Filter,
    CacheType.STICKINESS: StickinessFilter,
    CacheType.RETENTION: RetentionFilter,
    CacheType.PATHS: Filter,
    CacheType.FUNNEL: Filter,
}


def cached_function(cache_type: CacheType):
    def parameterized_decorator(f: Callable):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # prepare caching params
            request: HttpRequest = args[1]
            team = cast(User, request.user).team
            filter = None
            if not team:
                return f(*args, **kwargs)

            if cache_type == CacheType.FUNNEL:
                pk = args[2]
                cache_key = generate_cache_key("funnel_{}_{}".format(pk, team.pk))
                payload = {"funnel_id": pk, "team_id": team.pk}
            elif cache_type in [_cache_type.value for _cache_type in CacheType]:
                filter = TYPE_TO_FILTER[cache_type](request=request, team=team)
                cache_key = generate_cache_key(filter.toJSON() + "_" + str(team.pk))
                payload = {"filter": filter.toJSON(), "team_id": team.pk}
            else:
                raise ValueError("Invalid cache type!")
            # return cached result if possible
            if not request.GET.get("refresh", False):
                cached_result = cache.get(cache_key)
                if cached_result:
                    if is_ee_enabled() and settings.EE_AVAILABLE:
                        from ee.clickhouse.client import save_cache_call

                        save_cache_call()
                    return cached_result["result"]
            # call function being wrapped
            result = f(*args, **kwargs)

            # cache new data
            if result is not None:
                cache.set(
                    cache_key, {"result": result, "details": payload, "type": cache_type,}, CACHED_RESULTS_TTL,
                )
                if filter:
                    dashboard_items = DashboardItem.objects.filter(team_id=team.pk, filters_hash=cache_key)
                    dashboard_items.update(last_refresh=now())
            return result

        return wrapper

    return parameterized_decorator
