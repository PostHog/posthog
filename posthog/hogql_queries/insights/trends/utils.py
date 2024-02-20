from typing import List, Optional
from posthog.schema import SeriesType, EventsNode, BreakdownType


def series_event_name(series: SeriesType) -> str | None:
    if isinstance(series, EventsNode):
        return series.event
    return None


def get_properties_chain(
    breakdown_type: BreakdownType,
    breakdown_field: str,
    group_type_index: Optional[float | int],
) -> List[str | int]:
    if breakdown_type == "person":
        return ["person", "properties", breakdown_field]

    if breakdown_type == "session":
        return ["session", "duration"]

    if breakdown_type == "group" and group_type_index is not None:
        group_type_index_int = int(group_type_index)
        return [f"group_{group_type_index_int}", "properties", breakdown_field]
    elif breakdown_type == "group" and group_type_index is None:
        raise Exception("group_type_index missing from params")

    if breakdown_type == "data_warehouse":
        return [breakdown_field]

    return ["properties", breakdown_field]
