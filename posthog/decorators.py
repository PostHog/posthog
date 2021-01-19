from enum import Enum
from functools import wraps
from typing import Callable, cast

from django.core.cache import cache
from django.http.request import HttpRequest
from django.utils.timezone import now

from posthog.models import Filter, Team, User
from posthog.models.dashboard_item import DashboardItem
from posthog.models.filters.utils import get_filter
from posthog.settings import TEMP_CACHE_RESULTS_TTL
from posthog.utils import generate_cache_key

from .utils import generate_cache_key


class CacheType(str, Enum):
    TRENDS = "Trends"
    FUNNEL = "Funnel"
    RETENTION = "Retention"
    SESSION = "Session"
    STICKINESS = "Stickiness"
    PATHS = "Path"


def cached_function():
    def parameterized_decorator(f: Callable):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # prepare caching params
            request: HttpRequest = args[1]
            team = cast(User, request.user).team
            filter = None
            if not team:
                return f(*args, **kwargs)

            filter = get_filter(request=request, team=team)
            cache_key = generate_cache_key("{}_{}".format(filter.toJSON(), team.pk))
            payload = {"filter": filter.toJSON(), "team_id": team.pk}
            # return cached result if possible
            if not request.GET.get("refresh", False):
                cached_result = cache.get(cache_key)
                if cached_result and cached_result.get("result"):
                    return cached_result["result"]
            # call function being wrapped
            result = f(*args, **kwargs)

            # cache new data
            if result is not None and (not isinstance(result, dict) or not result.get("loading")):
                cache.set(
                    cache_key, {"result": result, "details": payload,}, TEMP_CACHE_RESULTS_TTL,
                )
                if filter:
                    dashboard_items = DashboardItem.objects.filter(team_id=team.pk, filters_hash=cache_key)
                    dashboard_items.update(last_refresh=now())
            return result

        return wrapper

    return parameterized_decorator
