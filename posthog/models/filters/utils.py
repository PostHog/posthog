from typing import Any, Dict, List, Optional, Union

from django.http import HttpRequest

from posthog.constants import INSIGHT_RETENTION, INSIGHT_SESSIONS, INSIGHT_TRENDS


def get_filter(team, data: dict = {}, request: Optional[HttpRequest] = None):
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
        return StickinessFilter(data=data, request=request, team=team)
    return Filter(data=data, request=request)
