from typing import List, Literal, Optional, Union
from posthog.schema import ActionsNode, EventsNode


def series_event_name(series: EventsNode | ActionsNode) -> str | None:
    if isinstance(series, EventsNode):
        return series.event
    return None


def get_properties_chain(
    breakdown_type: Union[Literal["person"], Literal["session"], Literal["group"], Literal["event"]],
    breakdown_field: str,
    group_type_index: Optional[float | int],
) -> List[str]:
    if breakdown_type == "person":
        return ["person", "properties", breakdown_field]

    if breakdown_type == "session":
        return ["session", "duration"]

    if breakdown_type == "group" and group_type_index is not None:
        group_type_index_int = int(group_type_index)
        return [f"group_{group_type_index_int}", "properties", breakdown_field]
    elif breakdown_type == "group" and group_type_index is None:
        raise Exception("group_type_index missing from params")

    return ["properties", breakdown_field]
