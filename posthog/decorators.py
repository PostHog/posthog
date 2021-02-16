from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Callable, Dict, List, Union, cast

from django.core.cache import cache
from django.http.request import HttpRequest
from django.utils.timezone import now

from posthog.models import Filter, Team, User
from posthog.models.dashboard_item import DashboardItem
from posthog.models.filters.utils import get_filter
from posthog.settings import TEMP_CACHE_RESULTS_TTL
from posthog.utils import generate_cache_key

from .utils import generate_cache_key, get_safe_cache


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
        def wrapper(*args, **kwargs) -> Dict[str, Union[List, datetime, bool]]:
            # prepare caching params
            request: HttpRequest = args[1]
            team = cast(User, request.user).team
            filter = None
            if not team:
                return f(*args, **kwargs)

            filter = get_filter(request=request, team=team)
            cache_key = generate_cache_key("{}_{}".format(filter.toJSON(), team.pk))
            # return cached result if possible
            if not request.GET.get("refresh", False):
                cached_result = get_safe_cache(cache_key)
                if cached_result and cached_result.get("result"):
                    return {**cached_result, "is_cached": True}
            # call function being wrapped
            result = f(*args, **kwargs)

            # cache new data
            if result is not None and not (isinstance(result.get("result"), dict) and result["result"].get("loading")):
                cache.set(
                    cache_key, {"result": result["result"], "last_refresh": now()}, TEMP_CACHE_RESULTS_TTL,
                )
                if filter:
                    dashboard_items = DashboardItem.objects.filter(team_id=team.pk, filters_hash=cache_key)
                    dashboard_items.update(last_refresh=now())
            return result

        return wrapper

    return parameterized_decorator
