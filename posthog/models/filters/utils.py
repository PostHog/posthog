from typing import Any, Dict, List, Optional, Union

from django.http import HttpRequest

from posthog.constants import INSIGHT_PATHS, INSIGHT_RETENTION, INSIGHT_SESSIONS, INSIGHT_TRENDS
from posthog.models.filters.path_filter import PathFilter


def get_filter(team, data: dict = {}, request: Optional[HttpRequest] = None):
    from posthog.models.event import Event
    from posthog.models.filters.filter import Filter
    from posthog.models.filters.retention_filter import RetentionFilter
    from posthog.models.filters.sessions_filter import SessionsFilter
    from posthog.models.filters.stickiness_filter import StickinessFilter

    insight = data.get("insight")
    if not insight and request:
        insight = request.GET.get("insight")
    if insight == INSIGHT_RETENTION:
        return RetentionFilter(data={**data, "insight": INSIGHT_RETENTION}, request=request)
    elif insight == INSIGHT_SESSIONS:
        return SessionsFilter(data={**data, "insight": INSIGHT_SESSIONS}, request=request)
    elif insight == INSIGHT_TRENDS and data.get("shown_as") == "Stickiness":
        earliest_timestamp_func = lambda team_id: Event.objects.earliest_timestamp(team_id)
        return StickinessFilter(data=data, request=request, team=team, get_earliest_timestamp=earliest_timestamp_func)
    elif insight == INSIGHT_PATHS:
        return PathFilter(data={**data, "insight": INSIGHT_PATHS}, request=request)
    return Filter(data=data, request=request)
