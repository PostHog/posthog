from datetime import datetime, timedelta
from math import ceil
from typing import Optional, Tuple, Union
from rest_framework import request

import pytz

from posthog.caching.calculate_results import calculate_cache_key
from posthog.caching.insight_caching_state import InsightCachingState
from posthog.models import DashboardTile, Insight
from posthog.models.filters.utils import get_filter
from posthog.utils import refresh_requested_by_client

"""
Utilities used by the insights API to determine whether
or not to refresh an insight upon a client request to do so
"""

# default minimum wait time for refreshing an insight
DEFAULT_CLIENT_INSIGHT_ALLOWED_REFRESH_FREQUENCY = timedelta(minutes=15)


# returns should_refresh, refresh_frequency
def should_refresh_insight(
    insight: Insight, dashboard_tile: Optional[DashboardTile], *, request: request.Request, is_shared=False
) -> Tuple[bool, timedelta]:
    filter = get_filter(
        data=insight.dashboard_filters(dashboard_tile.dashboard if dashboard_tile is not None else None),
        team=insight.team,
    )

    target: Union[Insight, DashboardTile] = insight if dashboard_tile is None else dashboard_tile
    cache_key = calculate_cache_key(target)
    caching_state = InsightCachingState.objects.filter(team_id=insight.team.pk, cache_key=cache_key, insight=insight)

    delta_days: Optional[int] = None
    if filter.date_from and filter.date_to:
        delta = filter.date_to - filter.date_from
        delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

    refresh_frequency = DEFAULT_CLIENT_INSIGHT_ALLOWED_REFRESH_FREQUENCY
    if (hasattr(filter, "interval") and filter.interval == "hour") or (delta_days is not None and delta_days <= 7):
        refresh_frequency = timedelta(minutes=3)

    refresh_insight_now = False
    if len(caching_state) == 0 or caching_state[0].last_refresh is None:
        # Always refresh if there are no cached results
        refresh_insight_now = True
    elif (refresh_requested_by_client(request) or is_shared) and (
        caching_state[0].last_refresh + refresh_frequency <= datetime.now(tz=pytz.timezone("UTC"))
    ):
        # Also refresh if the user has requested and refresh and enough time has passed since last refresh
        # We treat loading a shared dashboard/insight as a refresh request
        refresh_insight_now = True

    return refresh_insight_now, refresh_frequency
