from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Callable, Dict, List, TypeVar, Union, cast

from django.core.cache import cache
from django.utils.timezone import now
from rest_framework.request import Request

from posthog.models import Filter, Team, User
from posthog.models.dashboard_item import DashboardItem
from posthog.models.filters.utils import get_filter
from posthog.settings import TEMP_CACHE_RESULTS_TTL
from posthog.utils import should_refresh

from .utils import generate_cache_key, get_safe_cache


class CacheType(str, Enum):
    TRENDS = "Trends"
    FUNNEL = "Funnel"
    RETENTION = "Retention"
    SESSION = "Session"
    STICKINESS = "Stickiness"
    PATHS = "Path"


T = TypeVar("T")


def cached_function() -> Callable[[Callable[..., T]], Callable[..., T]]:
    def parameterized_decorator(f: Callable[..., T]) -> T:
        @wraps(f)
        def wrapper(*args, **kwargs) -> Dict[str, Union[List, datetime, bool, str]]:
            # prepare caching params
            request: Request = args[1]
            team = cast(User, request.user).team
            filter = None
            if not team:
                return f(*args, **kwargs)

            filter = get_filter(request=request, team=team)
            cache_key = generate_cache_key("{}_{}".format(filter.toJSON(), team.pk))

            # return cached result if possible
            if not should_refresh(request):
                cached_result = get_safe_cache(cache_key)
                if cached_result and cached_result.get("result"):
                    cached_result["is_cached"] = True
                    return cached_result

            # call function being wrapped
            fresh_result = cast(dict, f(*args, **kwargs))
            # cache new data
            if fresh_result is not None and not (
                isinstance(fresh_result.get("result"), dict) and fresh_result["result"].get("loading")
            ):
                fresh_result["last_refresh"] = now()
                cache.set(
                    cache_key, fresh_result, TEMP_CACHE_RESULTS_TTL,
                )
                if filter:
                    dashboard_items = DashboardItem.objects.filter(team_id=team.pk, filters_hash=cache_key)
                    dashboard_items.update(last_refresh=now())
            fresh_result["is_cached"] = False
            return fresh_result

        return wrapper

    return parameterized_decorator
