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

    # Prevent the same query from needlessly running concurrently
    is_refresh_currently_running = _is_refresh_currently_running_somewhere_else(caching_state, now)
    if refresh_insight_now and is_refresh_currently_running:
        assert caching_state is not None
        if not is_shared:
            # If this insight has been requested by a logged-in user, wait for the refresh to finish
            while is_refresh_currently_running:
                sleep(1)
                caching_state.refresh_from_db()
                has_refresh_completed = (
                    caching_state.last_refresh is not None
                    and caching_state.last_refresh >= caching_state.last_refresh_queued_at
                )
                if has_refresh_completed:
                    # Refreshed successfully! Refresh is no longer needed
                    refresh_insight_now = False
                    break
                is_refresh_currently_running = _is_refresh_currently_running_somewhere_else(
                    caching_state, datetime.now(tz=pytz.timezone("UTC"))
                )
        else:
            # Prevent concurrent refreshes of shared insights/dashboards from hammering ClickHouse plus from taking up
            # too many Nginx/Gunicorn connections. This means that if user B loads a shared insight/dashboard
            # that's currently being calculated for user A, user B will get stale results. That's intentional:
            # we just don't want to go down if some blog post with a PostHog iframe goes viral.
            refresh_insight_now = False

    return refresh_insight_now, refresh_frequency


def _is_refresh_currently_running_somewhere_else(caching_state: Optional[InsightCachingState], now: datetime) -> bool:
    """Return whether the refresh is most likely still running somewhere else."""
    if (
        caching_state is not None
        # A refresh must has queued at some point in the past
        and caching_state.last_refresh_queued_at is not None
        # That point was recent enough that the query might still be running
        and caching_state.last_refresh_queued_at > now - timedelta(seconds=CLICKHOUSE_MAX_EXECUTION_TIME)
        # And refreshing must have either never finished or last finished before it was queued now
        and (caching_state.last_refresh is None or caching_state.last_refresh < caching_state.last_refresh_queued_at)
    ):
        return True
    else:
        # Otherwise we're sure the refresh isn't running at the moment - either it's not been queued or it's timed out
        # (barring the occasional race condition related to fetching state from PG, but that much uncertainty is okay)
        return False
