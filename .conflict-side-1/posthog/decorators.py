from collections.abc import Callable
from enum import StrEnum
from functools import wraps
from typing import Any, TypeVar, Union, cast

from django.urls import resolve
from django.utils.timezone import now

from rest_framework.request import Request
from statshog.defaults.django import statsd

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.caching.utils import is_stale_filter
from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql_queries.legacy_compatibility.feature_flag import get_query_method
from posthog.models.filters.utils import get_filter
from posthog.utils import refresh_requested_by_client

from .utils import generate_cache_key, get_safe_cache


class CacheType(StrEnum):
    TRENDS = "Trends"
    FUNNEL = "Funnel"
    STICKINESS = "Stickiness"


ResultPackage = Union[dict[str, Any], list[dict[str, Any]]]

T = TypeVar("T", bound=ResultPackage)
U = TypeVar("U", bound=TeamAndOrgViewSetMixin)


def cached_by_filters(f: Callable[[U, Request], T]) -> Callable[[U, Request], T]:
    """Caches the decorated method on a ViewSet in Redis. Used for anything based
    on a filter e.g. insights or persons calculations.

    The decorated method is expected to return a dict with key `result`. Keys
    `last_refresh` and `is_cached` are added for the full result package.

    The cache can be invalidated by using the boolean key `refresh` or setting
    a `cache_invalidation_key` which gets incorporated in the cache key.
    """

    @wraps(f)
    def wrapper(self: U, request: Request) -> T:
        from posthog.caching.insight_cache import update_cached_state

        # prepare caching params
        team = self.team
        if not team:
            return f(self, request)

        filter = get_filter(request=request, team=team)
        query_method = get_query_method(request=request, team=team)
        cache_key = f"{filter.toJSON()}_{team.pk}"

        if query_method == "hogql":
            cache_key += "_hogql"

        if request.data.get("cache_invalidation_key"):
            cache_key += f"_{request.data['cache_invalidation_key']}"

        if request.GET.get("cache_invalidation_key"):
            cache_key += f"_{request.GET['cache_invalidation_key']}"

        cache_key = generate_cache_key(cache_key)

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
                if not is_stale_filter(team, filter, cached_result_package):
                    cached_result_package["is_cached"] = True
                    statsd.incr("posthog_cached_function_cache_hit", tags={"route": route})
                    return cached_result_package
                else:
                    statsd.incr("posthog_cached_function_cache_stale", tags={"route": route})
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
                fresh_result_package["query_method"] = query_method
                update_cached_state(team.pk, cache_key, timestamp, fresh_result_package)

        return fresh_result_package

    return wrapper
