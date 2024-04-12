from typing import Any, Dict, List
from uuid import uuid4

Event = Dict[str, Any]

event_properties_to_keep = [
    "$viewport_height",
    "$viewport_width",
    "$session_id",
    "distinct_id",
    "$current_url",
    "token",
]


def extract_heatmap_events(events: List[Event]) -> List[Event]:
    """
    To save on data transfer and simplify the event processing, we piggyback $heatmap events on top of existing events

    """
    heatmap_events: List[Event] = []

    for event in events:
        heatmap_data = event["properties"].pop("$heatmap_data", None)

        if heatmap_data:
            heatmap_event: Dict = {
                "event": "$heatmap",
                "uuid": str(uuid4()),
                "properties": {
                    "$heatmap_data": heatmap_data,
                },
                "timestamp": event.get("timestamp"),
            }

            # Only copy the event data we need:
            for prop in event_properties_to_keep:
                heatmap_event["properties"][prop] = event["properties"].get(prop, None)

            heatmap_events.append(heatmap_event)

    return events + heatmap_events
