from typing import Any, Literal, cast

from rest_framework.exceptions import ValidationError

from posthog.constants import GROUP_TYPES_LIMIT

GroupTypeIndex = Literal[0, 1, 2, 3, 4]


def earliest_timestamp_func(team_id: int):
    # Imported here to break a circular import: hogql_queries pulls in filter machinery.
    from posthog.hogql_queries.utils.timestamp_utils import get_earliest_timestamp_unfiltered  # noqa: PLC0415
    from posthog.models.team import Team  # noqa: PLC0415

    return get_earliest_timestamp_unfiltered(Team.objects.get(pk=team_id))


def validate_group_type_index(param_name: str, value: Any, required=False) -> GroupTypeIndex | None:
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

    return cast(GroupTypeIndex | None, value)
