from typing import Optional, Union

from posthog.schema import (
    ActionsNode,
    BaseMathType,
    BreakdownType,
    DataWarehouseNode,
    EventsNode,
    MultipleBreakdownType,
)

from posthog.constants import UNIQUE_GROUPS


def series_event_name(series: Union[EventsNode, ActionsNode, DataWarehouseNode]) -> str | None:
    if isinstance(series, EventsNode):
        return series.event
    return None


def get_properties_chain(
    breakdown_type: BreakdownType | MultipleBreakdownType | None,
    breakdown_field: str,
    group_type_index: Optional[float | int],
) -> list[str | int]:
    if breakdown_type == "person":
        if breakdown_field.startswith("$virt_"):
            # Virtual properties exist as expression fields on the persons table
            return ["person", breakdown_field]
        else:
            return ["person", "properties", breakdown_field]

    if breakdown_type == "session":
        return ["session", breakdown_field]

    if breakdown_type == "group" and group_type_index is not None:
        group_type_index_int = int(group_type_index)
        if breakdown_field.startswith("$virt_"):
            # Virtual properties exist as expression fields on the groups table
            return [f"group_{group_type_index_int}", breakdown_field]
        else:
            return [f"group_{group_type_index_int}", "properties", breakdown_field]
    elif breakdown_type == "group" and group_type_index is None:
        raise Exception("group_type_index missing from params")

    if breakdown_type == "data_warehouse":
        return [*breakdown_field.split(".")]

    if breakdown_type == "data_warehouse_person_property":
        return ["person", *breakdown_field.split(".")]

    return ["properties", breakdown_field]


def is_groups_math(series: Union[EventsNode, ActionsNode, DataWarehouseNode]) -> bool:
    return (
        series.math in {BaseMathType.DAU, UNIQUE_GROUPS, BaseMathType.WEEKLY_ACTIVE, BaseMathType.MONTHLY_ACTIVE}
        and series.math_group_type_index is not None
    )
