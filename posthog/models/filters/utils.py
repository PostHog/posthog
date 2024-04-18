from typing import Any, Literal, Optional

from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.constants import (
    GROUP_TYPES_LIMIT,
    INSIGHT_FUNNELS,
    INSIGHT_PATHS,
    INSIGHT_RETENTION,
    INSIGHT_STICKINESS,
    INSIGHT_TRENDS,
)

GroupTypeIndex = Literal[0, 1, 2, 3, 4]


def earliest_timestamp_func(team_id: int):
    from posthog.queries.util import get_earliest_timestamp

    return get_earliest_timestamp(team_id)


def get_filter(team, data: Optional[dict] = None, request: Optional[Request] = None):
    from .filter import Filter
    from .path_filter import PathFilter
    from .retention_filter import RetentionFilter
    from .stickiness_filter import StickinessFilter

    if data is None:
        data = {}
    insight = data.get("insight")
    if not insight and request:
        insight = request.GET.get("insight") or request.data.get("insight")
    if insight == INSIGHT_RETENTION:
        return RetentionFilter(data={**data, "insight": INSIGHT_RETENTION}, request=request, team=team)
    elif insight == INSIGHT_STICKINESS or (insight == INSIGHT_TRENDS and data.get("shown_as") == "Stickiness"):
        return StickinessFilter(
            data=data,
            request=request,
            team=team,
            get_earliest_timestamp=earliest_timestamp_func,
        )
    elif insight == INSIGHT_PATHS:
        return PathFilter(data={**data, "insight": INSIGHT_PATHS}, request=request, team=team)
    elif insight == INSIGHT_FUNNELS:
        return Filter(
            data={
                **data,
                **(request.data if request else {}),
                "insight": INSIGHT_FUNNELS,
            },
            request=request,
            team=team,
        )
    return Filter(data=data, request=request, team=team)


def validate_group_type_index(param_name: str, value: Any, required=False) -> Optional[GroupTypeIndex]:
    error = ValidationError(
        f"{param_name} is required to be at least 0 and less than {GROUP_TYPES_LIMIT}",
        code="invalid",
    )

    if required and value is None:
        raise error

    if value is not None:
        try:
            value = int(value)
        except:
            raise error
        if not (0 <= value < GROUP_TYPES_LIMIT):
            raise error

    return value
