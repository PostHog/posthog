from typing import Any, Dict, List, Optional, Union

from rest_framework.request import Request

from posthog.constants import (
    INSIGHT_FUNNELS,
    INSIGHT_PATHS,
    INSIGHT_RETENTION,
    INSIGHT_SESSIONS,
    INSIGHT_STICKINESS,
    INSIGHT_TRENDS,
)
from posthog.models.filters.path_filter import PathFilter
from posthog.utils import is_clickhouse_enabled


def earliest_timestamp_func(team_id: int):
    if is_clickhouse_enabled():
        from ee.clickhouse.queries.util import get_earliest_timestamp

        return get_earliest_timestamp(team_id)
    from posthog.models.event import Event

    return Event.objects.earliest_timestamp(team_id)


def get_filter(team, data: dict = {}, request: Optional[Request] = None):
    from posthog.models.filters.filter import Filter
    from posthog.models.filters.retention_filter import RetentionFilter
    from posthog.models.filters.sessions_filter import SessionsFilter
    from posthog.models.filters.stickiness_filter import StickinessFilter

    insight = data.get("insight")
    if not insight and request:
        insight = request.GET.get("insight") or request.data.get("insight")
    if insight == INSIGHT_RETENTION:
        return RetentionFilter(data={**data, "insight": INSIGHT_RETENTION}, request=request)
    elif insight == INSIGHT_SESSIONS:
        return SessionsFilter(data={**data, "insight": INSIGHT_SESSIONS}, request=request)
    elif insight == INSIGHT_STICKINESS or (insight == INSIGHT_TRENDS and data.get("shown_as") == "Stickiness"):
        return StickinessFilter(data=data, request=request, team=team, get_earliest_timestamp=earliest_timestamp_func)
    elif insight == INSIGHT_PATHS:
        return PathFilter(data={**data, "insight": INSIGHT_PATHS}, request=request)
    elif insight == INSIGHT_FUNNELS:
        return Filter(data={**data, **(request.data if request else {}), "insight": INSIGHT_FUNNELS}, request=request)
    return Filter(data=data, request=request)
