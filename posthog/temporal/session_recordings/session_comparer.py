from typing import Any
import json


def is_click(event: dict) -> bool:
    """Check if event is a click event."""
    CLICK_TYPES = [2, 4, 9, 3]  # Click, DblClick, TouchEnd, ContextMenu
    return (
        event.get("type") == 3  # RRWebEventType.IncrementalSnapshot
        and event.get("data", {}).get("source") == 2  # RRWebEventSource.MouseInteraction
        and event.get("data", {}).get("type") in CLICK_TYPES
    )


def is_mouse_activity(event: dict) -> bool:
    """Check if event is a mouse activity event."""
    MOUSE_ACTIVITY_SOURCES = [2, 1, 6]  # MouseInteraction, MouseMove, TouchMove
    return (
        event.get("type") == 3  # RRWebEventType.IncrementalSnapshot
        and event.get("data", {}).get("source") in MOUSE_ACTIVITY_SOURCES
    )


def is_keypress(event: dict) -> bool:
    """Check if event is a keypress event."""
    return (
        event.get("type") == 3  # RRWebEventType.IncrementalSnapshot
        and event.get("data", {}).get("source") == 5  # RRWebEventSource.Input
    )


def is_console_log(event: dict) -> bool:
    """Check if event is a console log event."""
    return (
        event.get("type") == 6  # RRWebEventType.Plugin
        and event.get("data", {}).get("plugin") == "rrweb/console@1"
    )


def get_console_level(event: dict) -> str | None:
    """Get console log level from event."""
    if not is_console_log(event):
        return None
    return event.get("data", {}).get("payload", {}).get("level")


def get_url_from_event(event: dict) -> str | None:
    """Extract URL from event using same logic as hrefFrom in rrweb-types.ts."""
    data = event.get("data", {})
    if not isinstance(data, dict):
        return None

    meta_href = data.get("href", "")
    meta_href = meta_href.strip() if isinstance(meta_href, str) else ""

    payload = data.get("payload", {})
    payload_href = payload.get("href", "") if isinstance(payload, dict) else ""
    payload_href = payload_href.strip() if isinstance(payload_href, str) else ""

    return meta_href or payload_href or None


def add_url(url_set: set[str], url: str, max_url_length: int = 4 * 1024, max_urls: int = 25) -> None:
    """Add URL to set with same constraints as snappy-session-recorder.ts."""
    if not url:
        return
    if len(url) > max_url_length:
        url = url[:max_url_length]
    if len(url_set) < max_urls:
        url_set.add(url)


def count_events_per_window(events: dict[str, int]) -> dict[str | None, int]:
    """Count events per window ID."""
    window_counts: dict[str | None, int] = {}
    for event_json, count in events.items():
        window_id, _ = json.loads(event_json)
        # Convert "null" string to None if needed (in case of JSON serialization)
        if isinstance(window_id, str) and window_id.lower() == "null":
            window_id = None
        window_counts[window_id] = window_counts.get(window_id, 0) + count
    return window_counts


def group_events_by_type(events: dict[str, int]) -> dict[str, int]:
    """Group events by their type."""
    type_counts: dict[str, int] = {}
    for event, count in events.items():
        _, data = json.loads(event)
        event_type = str(data.get("type", "unknown"))
        type_counts[event_type] = type_counts.get(event_type, 0) + count
    return type_counts


def get_structure(obj: Any, max_depth: int = 10) -> Any:
    """Get the structure of an object without its values."""
    if max_depth <= 0:
        return "..."

    if isinstance(obj, dict):
        return {k: get_structure(v, max_depth - 1) for k, v in obj.items()}
    elif isinstance(obj, list):
        if not obj:
            return []
        # Just show structure of first item for arrays
        return [get_structure(obj[0], max_depth - 1)]
    elif isinstance(obj, str | int | float | bool):
        return type(obj).__name__
    elif obj is None:
        return None
    return type(obj).__name__


def transform_v2_snapshot(raw_snapshot: list) -> dict:
    """Transform v2 snapshot format [windowId, serializedEvent] into {window_id, data} format."""
    if not isinstance(raw_snapshot, list) or len(raw_snapshot) != 2:
        raise ValueError("Invalid v2 snapshot format")

    window_id, event = raw_snapshot
    return {"window_id": window_id, "data": event}


def transform_v1_snapshots(snapshots: list[dict]) -> list[dict]:
    """Transform v1 snapshots from [{windowId, data: [event]}] to [{windowId, data: event}]."""
    flattened = []
    for snapshot in snapshots:
        window_id = snapshot.get("window_id")
        data_array = snapshot.get("data", [])
        if not isinstance(data_array, list):
            continue

        for event in data_array:
            flattened.append({"window_id": window_id, "data": event})
    return flattened
