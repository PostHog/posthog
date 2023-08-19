from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, TypeVar, Union, cast
from zoneinfo import ZoneInfo

import posthoganalytics
from django.urls import resolve
from django.utils.timezone import now
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet
from statshog.defaults.django import statsd

from posthog.clickhouse.query_tagging import tag_queries
from posthog.cloud_utils import is_cloud
from posthog.datetime import start_of_day, start_of_hour, start_of_month, start_of_week
from posthog.models import User
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import get_filter
from posthog.models.team.team import Team
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


def cached_by_filters(f: Callable[[U, Request], T]) -> Callable[[U, Request], T]:
    """Caches the decorated method on a ViewSet in Redis. Used for anything based
    on a filter e.g. insights or persons calculations.

    The decorated method is expected to return a dict with key `result`. Keys
    `last_refresh` and `is_cached` are added for the full result package.

    The cache can be invalidated by using the boolean key `refresh` or setting
    a `cache_invalidation_key` which gets incorporated in the cache key.
    """

    @wraps(f)
    def wrapper(self, request) -> T:
        from posthog.caching.insight_cache import update_cached_state

        # prepare caching params
        team = cast(User, request.user).team
        if not team:
            return f(self, request)

        filter = get_filter(request=request, team=team)
        cache_key = f"{filter.toJSON()}_{team.pk}"
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
                if not is_stale(team, filter, cached_result_package):
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
                update_cached_state(team.pk, cache_key, timestamp, fresh_result_package)

        return fresh_result_package

    return wrapper


def stale_cache_invalidation_disabled(team: Team) -> bool:
    """Can be disabled temporarly to help in cases of service degradation."""
    if is_cloud():  # on PostHog Cloud, use the feature flag
        return not posthoganalytics.feature_enabled(
            "stale-cache-invalidation-enabled",
            str(team.uuid),
            groups={"organization": str(team.organization.id)},
            group_properties={
                "organization": {"id": str(team.organization.id), "created_at": team.organization.created_at}
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    else:
        return False


def is_stale(team: Team, filter: Filter | RetentionFilter | StickinessFilter | PathFilter, cached_result: Any) -> bool:
    """Indicates wether a cache item is obviously outdated based on filters,
    i.e. the next time interval was entered since the last computation. For
    example an insight with -7d date range that was last computed yesterday.
    The same insight refreshed today wouldn't be marked as stale.
    """

    if stale_cache_invalidation_disabled(team):
        return False

    last_refresh = cached_result.get("last_refresh", None)
    date_to = min([filter.date_to, datetime.now(tz=ZoneInfo("UTC"))])  # can't be later than now

    if last_refresh is None:  # safeguard
        return False

    if isinstance(filter, Filter):
        if filter.interval == "hour":
            return start_of_hour(date_to) > start_of_hour(last_refresh)
        elif filter.interval == "day":
            return start_of_day(date_to) > start_of_day(last_refresh)
        elif filter.interval == "week":
            return start_of_week(date_to) > start_of_week(last_refresh)
        elif filter.interval == "month":
            return start_of_month(date_to) > start_of_month(last_refresh)

    return False
