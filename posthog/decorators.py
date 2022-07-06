from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, TypeVar, Union, cast

from django.conf import settings
from django.core.cache import cache
from django.utils.timezone import now
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet

from posthog.models import DashboardTile, User
from posthog.models.filters.utils import get_filter
from posthog.models.insight import Insight
from posthog.utils import should_refresh

from .utils import generate_cache_key, get_safe_cache


class CacheType(str, Enum):
    TRENDS = "Trends"
    FUNNEL = "Funnel"
    RETENTION = "Retention"
    STICKINESS = "Stickiness"
    PATHS = "Path"


ResultPackage = Union[Dict[str, Any], List[Dict[str, Any]]]

T = TypeVar("T", bound=ResultPackage)
U = TypeVar("U", bound=GenericViewSet)


def cached_function(f: Callable[[U, Request], T]) -> Callable[[U, Request], T]:
    @wraps(f)
    def wrapper(self, request) -> T:
        # prepare caching params
        team = cast(User, request.user).team
        if not team:
            return f(self, request)

        filter = get_filter(request=request, team=team)
        cache_key = generate_cache_key(f"{filter.toJSON()}_{team.pk}")

        # return cached result when possible
        if not should_refresh(request):
            cached_result_package = get_safe_cache(cache_key)
            if cached_result_package and cached_result_package.get("result"):
                cached_result_package["is_cached"] = True
                return cached_result_package

        # call function being wrapped
        fresh_result_package = cast(T, f(self, request))
        # cache new data
        if isinstance(fresh_result_package, dict):
            result = fresh_result_package.get("result")
            if not isinstance(result, dict) or not result.get("loading"):
                fresh_result_package["last_refresh"] = now()
                fresh_result_package["is_cached"] = False
                cache.set(
                    cache_key, fresh_result_package, settings.CACHED_RESULTS_TTL,
                )
                if filter:
                    Insight.objects.filter(team_id=team.pk, filters_hash=cache_key).update(last_refresh=now())

                    DashboardTile.objects.filter(insight__team_id=team.pk, filters_hash=cache_key).update(
                        last_refresh=now()
                    )

        return fresh_result_package

    return wrapper
