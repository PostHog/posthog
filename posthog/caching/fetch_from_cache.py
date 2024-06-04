from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from prometheus_client import Counter

from posthog.schema import QueryTiming

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
    timings: Optional[list[QueryTiming]] = None
    columns: Optional[list] = None


@dataclass(frozen=True)
class NothingInCacheResult(InsightResult):
    result: Optional[Any] = None
    last_refresh: Optional[datetime] = None
    cache_key: Optional[str] = None
    is_cached: bool = False
    timezone: Optional[str] = None
    next_allowed_client_refresh: Optional[datetime] = None
    columns: Optional[list] = None


"""
def synchronously_update_cache(
    insight: Insight,
    dashboard: Optional[Dashboard],
    refresh_frequency: Optional[timedelta] = None,
) -> InsightResult:
    cache_key, cache_type, result = calculate_for_filter_based_insight(insight, dashboard)
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
"""
