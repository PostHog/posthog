from typing import Any, Dict, List
from uuid import uuid4
from urllib.parse import urlparse, urlunparse

Event = Dict[str, Any]

event_properties_to_keep = [
    "$viewport_height",
    "$viewport_width",
    "$session_id",
    "distinct_id",
    "$current_url",
    "token",
]


def replace_path_in_url(url, new_path):
    parsed_url = urlparse(url)
    new_url = urlunparse((parsed_url.scheme, parsed_url.netloc, new_path, "", "", ""))
    return new_url


def extract_heatmap_events(events: List[Event]) -> List[Event]:
    """
    To save on data transfer and simplify the event processing, we piggyback $heatmap events on top of existing events

    """
    heatmap_events: List[Event] = []

    for event in events:
        # { "{url}": [ { "x": 0, "y": 0, "target_fixed": false, "type": "click" } ] }
        heatmap_data = event["properties"].pop("$heatmap_data", None)

        # Slight optimization: We derive heatmap data for scrolling from existing scroll properties
        prev_pageview_pathname = event["properties"].get("$prev_pageview_pathname", None)
        prev_pageview_max_scroll = event["properties"].get("$prev_pageview_max_scroll", None)
        current_url = event["properties"].get("$current_url", None)

        if prev_pageview_pathname and current_url:
            if not heatmap_data:
                heatmap_data = {}

            # TRICKY: We need to combine the current_url with the prev_pageview_pathname
            previous_url = replace_path_in_url(current_url, prev_pageview_pathname)
            heatmap_data[previous_url] = heatmap_data.get(previous_url, [])
            heatmap_data[previous_url].append(
                {
                    "x": 0,
                    "y": prev_pageview_max_scroll,
                    "target_fixed": False,
                    "type": "scrolldepth",
                }
            )

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
