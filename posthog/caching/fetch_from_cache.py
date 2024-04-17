from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, List, Optional, Union

from django.utils.timezone import now
from prometheus_client import Counter

from posthog.caching.calculate_results import (
    calculate_cache_key,
    calculate_result_by_insight,
)
from posthog.caching.insight_cache import update_cached_state
from posthog.models import DashboardTile, Insight
from posthog.models.dashboard import Dashboard
from posthog.schema import QueryTiming
from posthog.utils import get_safe_cache

insight_cache_read_counter = Counter(
    "posthog_cloud_insight_cache_read",
    "A read from the redis insight cache",
    labelnames=["result"],
)


@dataclass(frozen=True)
class InsightResult:
    result: Optional[Any]
    last_refresh: Optional[datetime]
    cache_key: Optional[str]
    is_cached: bool
    timezone: Optional[str]
    next_allowed_client_refresh: Optional[datetime] = None
    timings: Optional[List[QueryTiming]] = None


@dataclass(frozen=True)
class NothingInCacheResult(InsightResult):
    result: Optional[Any] = None
    last_refresh: Optional[datetime] = None
    cache_key: Optional[str] = None
    is_cached: bool = False
    timezone: Optional[str] = None
    next_allowed_client_refresh: Optional[datetime] = None


def fetch_cached_insight_result(target: Union[Insight, DashboardTile], refresh_frequency: timedelta) -> InsightResult:
    """
    Returns cached value for this insight.

    InsightResult.result will be None if value was not found in cache.
    """

    cache_key = calculate_cache_key(target)

    if cache_key is None:
        return NothingInCacheResult(cache_key=None)

    cached_result = get_safe_cache(cache_key)

    if cached_result is None:
        insight_cache_read_counter.labels("cache_miss").inc()
        return NothingInCacheResult(cache_key=cache_key)
    else:
        insight_cache_read_counter.labels("cache_hit").inc()
        last_refresh = cached_result.get("last_refresh")
        next_allowed_client_refresh = (
            cached_result.get("next_allowed_client_refresh") or last_refresh + refresh_frequency
        )

        return InsightResult(
            result=cached_result.get("result"),
            last_refresh=last_refresh,
            cache_key=cache_key,
            is_cached=True,
            # :TODO: This is only populated in some code paths writing to cache
            timezone=cached_result.get("timezone"),
            next_allowed_client_refresh=next_allowed_client_refresh,
        )


def synchronously_update_cache(
    insight: Insight,
    dashboard: Optional[Dashboard],
    refresh_frequency: Optional[timedelta] = None,
) -> InsightResult:
    cache_key, cache_type, result = calculate_result_by_insight(team=insight.team, insight=insight, dashboard=dashboard)
    timestamp = now()

    next_allowed_client_refresh = timestamp + refresh_frequency if refresh_frequency else None
    update_cached_state(
        insight.team_id,
        cache_key,
        timestamp,
        {
            "result": result,
            "type": cache_type,
            "last_refresh": timestamp,
            "next_allowed_client_refresh": next_allowed_client_refresh,
        },
    )

    return InsightResult(
        result=result,
        last_refresh=timestamp,
        cache_key=cache_key,
        is_cached=False,
        timezone=insight.team.timezone,
        next_allowed_client_refresh=next_allowed_client_refresh,
    )
