from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Optional, Tuple, Union

import pytz
from django.utils.timezone import now
from statshog.defaults.django import statsd

from posthog.caching.calculate_results import calculate_cache_key, calculate_result_by_insight
from posthog.caching.insight_cache import update_cached_state
from posthog.caching.insight_caching_state import InsightCachingState
from posthog.models import DashboardTile, Insight
from posthog.models.dashboard import Dashboard
from posthog.models.filters.utils import get_filter
from posthog.utils import get_safe_cache

# default minimum wait time for refreshing an insight
DEFAULT_INSIGHT_REFRESH_FREQUENCY = timedelta(minutes=15)


@dataclass(frozen=True)
class InsightResult:
    result: Optional[Any]
    last_refresh: Optional[datetime]
    cache_key: Optional[str]
    is_cached: bool
    timezone: Optional[str]
    next_allowed_refresh: Optional[datetime] = None


@dataclass(frozen=True)
class NothingInCacheResult(InsightResult):
    result: Optional[Any] = None
    last_refresh: Optional[datetime] = None
    cache_key: Optional[str] = None
    is_cached: bool = False
    timezone: Optional[str] = None
    next_allowed_refresh: Optional[datetime] = None


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
        statsd.incr("posthog_cloud_insight_cache_miss")
        return NothingInCacheResult(cache_key=cache_key)
    else:
        statsd.incr("posthog_cloud_insight_cache_hit")
        last_refresh = cached_result.get("last_refresh")
        next_allowed_refresh = cached_result.get("next_allowed_refresh") or last_refresh + refresh_frequency

        return InsightResult(
            result=cached_result.get("result"),
            last_refresh=last_refresh,
            cache_key=cache_key,
            is_cached=True,
            # :TODO: This is only populated in some code paths writing to cache
            timezone=cached_result.get("timezone"),
            next_allowed_refresh=next_allowed_refresh,
        )


def synchronously_update_cache(
    insight: Insight, dashboard: Optional[Dashboard], refresh_frequency: Optional[timedelta] = None
) -> InsightResult:
    cache_key, cache_type, result = calculate_result_by_insight(team=insight.team, insight=insight, dashboard=dashboard)
    timestamp = now()

    next_allowed_refresh = timestamp + refresh_frequency if refresh_frequency else None
    update_cached_state(
        insight.team_id,
        cache_key,
        timestamp,
        {"result": result, "type": cache_type, "last_refresh": timestamp, "next_allowed_refresh": next_allowed_refresh},
    )

    return InsightResult(
        result=result,
        last_refresh=timestamp,
        cache_key=cache_key,
        is_cached=False,
        timezone=insight.team.timezone,
        next_allowed_refresh=next_allowed_refresh,
    )


# returns should_refresh, refresh_frequency
def should_refresh_insight(insight: Insight, dashboard_tile: Optional[DashboardTile]) -> Tuple[bool, timedelta]:
    filter_data_with_dashboard_filters = insight.dashboard_filters(
        dashboard_tile.dashboard if dashboard_tile is not None else None
    )
    filter = get_filter(
        data=filter_data_with_dashboard_filters if filter_data_with_dashboard_filters is not None else {},
        team=insight.team,
    )

    target = insight if dashboard_tile is None else dashboard_tile
    cache_key = calculate_cache_key(target)
    caching_state = InsightCachingState.objects.filter(team_id=insight.team.pk, cache_key=cache_key, insight=insight)

    refresh_frequency = DEFAULT_INSIGHT_REFRESH_FREQUENCY

    delta_days: Optional[int] = None

    if filter.date_from and filter.date_to:
        delta = filter.date_to - filter.date_from
        delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

    if (hasattr(filter, "interval") and filter.interval == "hour") or (delta_days is not None and delta_days <= 7):
        refresh_frequency = timedelta(minutes=3)

    if len(caching_state) == 0 or caching_state[0].last_refresh is None:
        return True, refresh_frequency

    return caching_state[0].last_refresh + refresh_frequency <= datetime.now(tz=pytz.timezone("UTC")), refresh_frequency
