from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, TypeVar, Union, cast

from django.urls import resolve
from django.utils.timezone import now
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet
from statshog.defaults.django import statsd

from posthog.clickhouse.query_tagging import tag_queries
from posthog.models import User
from posthog.models.filters.utils import get_filter
from posthog.utils import refresh_requested_by_client

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
        from posthog.caching.insight_cache import update_cached_state

        # prepare caching params
        team = cast(User, request.user).team
        if not team:
            return f(self, request)

        filter = get_filter(request=request, team=team)
        cache_key = generate_cache_key(f"{filter.toJSON()}_{team.pk}")

        tag_queries(cache_key=cache_key)

        # return cached result when possible
        if not refresh_requested_by_client(request):
            cached_result_package = get_safe_cache(cache_key)

            # ignore the bare exception warning. we never want this to fail
            # noinspection PyBroadException
            try:
                route = resolve(request.path).route
            except:
                route = "unknown"

            if cached_result_package and cached_result_package.get("result"):
                cached_result_package["is_cached"] = True
                statsd.incr("posthog_cached_function_cache_hit", tags={"route": route})
                return cached_result_package
            else:
                statsd.incr("posthog_cached_function_cache_miss", tags={"route": route})

        # call function being wrapped
        fresh_result_package = cast(T, f(self, request))
        if isinstance(fresh_result_package, dict):
            result = fresh_result_package.get("result")
            if not isinstance(result, dict) or not result.get("loading"):
                timestamp = now()
                fresh_result_package["last_refresh"] = timestamp
                fresh_result_package["is_cached"] = False
                update_cached_state(team.pk, cache_key, timestamp, fresh_result_package)

        return fresh_result_package

    return wrapper
