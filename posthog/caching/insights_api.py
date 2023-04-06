from datetime import datetime, timedelta
from math import ceil
from time import sleep
from typing import Optional, Tuple, Union
from rest_framework import request

import pytz

from posthog.caching.calculate_results import CLICKHOUSE_MAX_EXECUTION_TIME, calculate_cache_key
from posthog.caching.insight_caching_state import InsightCachingState
from posthog.models import DashboardTile, Insight
from posthog.models.filters.utils import get_filter
from posthog.utils import refresh_requested_by_client

"""
Utilities used by the insights API to determine whether
or not to refresh an insight upon a client request to do so
"""

# Default minimum wait time for refreshing an insight
BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL = timedelta(minutes=15)
# Wait time for short-term insights
REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL = timedelta(minutes=3)
# Wait time for insights on shared insight/dashboard pages
INCREASED_MINIMUM_INSIGHT_REFRESH_INTERVAL = timedelta(minutes=30)


def should_refresh_insight(
    insight: Insight, dashboard_tile: Optional[DashboardTile], *, request: request.Request, is_shared=False
) -> Tuple[bool, timedelta]:
    """Return whether the insight should be refreshed now, and what's the minimum wait time between refreshes.

    If a refresh already is being processed somewhere else, this function will wait for that to finish (or time out).
    """
    now = datetime.now(tz=pytz.timezone("UTC"))
    filter = get_filter(
        data=insight.dashboard_filters(dashboard_tile.dashboard if dashboard_tile is not None else None),
        team=insight.team,
    )

    target: Union[Insight, DashboardTile] = insight if dashboard_tile is None else dashboard_tile
    cache_key = calculate_cache_key(target)
    # Most recently queued caching state
    caching_state = (
        InsightCachingState.objects.filter(team_id=insight.team.pk, cache_key=cache_key, insight=insight)
        .order_by("-last_refresh_queued_at")
        .first()
    )

    delta_days: Optional[int] = None
    if filter.date_from and filter.date_to:
        delta = filter.date_to - filter.date_from
        delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

    refresh_frequency = BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
    if getattr(filter, "interval", None) == "hour" or (delta_days is not None and delta_days <= 7):
        if not is_shared:  # The interval is always longer for shared insights/dashboard
            refresh_frequency = REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
    elif is_shared:  # The interval is always longer for shared insights/dashboard
        refresh_frequency = INCREASED_MINIMUM_INSIGHT_REFRESH_INTERVAL

    refresh_insight_now = False
    if caching_state is None or caching_state.last_refresh is None:
        refresh_insight_now = True
    # Only refresh if the user has requested a refresh or if we're on a shared dashboard/insight
    # (those have no explicit way of reloading)
    elif refresh_requested_by_client(request) or is_shared:
        refresh_insight_now = caching_state.last_refresh + refresh_frequency <= now

    # Check if the refresh is might already be running for this cache key - if so, let's wait until that's done
    if refresh_insight_now and caching_state is not None:
        refresh_insight_now = _wait_until_refresh_must_be_done(caching_state, now)

    return refresh_insight_now, refresh_frequency


def _wait_until_refresh_must_be_done(caching_state: InsightCachingState, now: datetime) -> bool:
    while (
        # A refresh must have been queued at some point in the past
        caching_state.last_refresh_queued_at is not None
        # That point must be recent enough that the query might still be running
        and caching_state.last_refresh_queued_at > now - timedelta(seconds=CLICKHOUSE_MAX_EXECUTION_TIME)
        # Also, refreshing must have either never finished or last finished before it was queued now
        and (caching_state.last_refresh is None or caching_state.last_refresh < caching_state.last_refresh_queued_at)
    ):
        # This looks a bit ugly because it blocks the thread, but it's BETTER than running the already-running query
        # from this thread concurrently. Either way we have to wait for results, this way just hammers the DB less
        sleep(3)
        caching_state.refresh_from_db()
        if (
            caching_state.last_refresh is not None
            and caching_state.last_refresh >= caching_state.last_refresh_queued_at
        ):
            # Refreshed successfully! Refresh is no longer needed
            return False
    else:
        # Otherwise we're sure the refresh isn't running at the moment - either it's not been queued or it's timed out
        # (barring the occasional race condition related to fetching state from PG, but that much uncertainty is okay)
        return True
