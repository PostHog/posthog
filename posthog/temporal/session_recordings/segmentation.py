from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Optional


class RRWebEventType(IntEnum):
    """RRWeb event types ported from rrweb-types.ts"""

    DomContentLoaded = 0
    Load = 1
    FullSnapshot = 2
    IncrementalSnapshot = 3
    Meta = 4
    Custom = 5
    Plugin = 6


class RRWebEventSource(IntEnum):
    """RRWeb event sources ported from rrweb-types.ts"""

    Mutation = 0
    MouseMove = 1
    MouseInteraction = 2
    Scroll = 3
    ViewportResize = 4
    Input = 5
    TouchMove = 6
    MediaInteraction = 7
    StyleSheetRule = 8
    CanvasMutation = 9
    Font = 10
    Log = 11
    Drag = 12
    StyleDeclaration = 13


# V1 implementation uses raw numbers
V1_ACTIVE_SOURCES = [1, 2, 3, 4, 5, 6, 7, 12]

# V2 implementation uses enum
V2_ACTIVE_SOURCES = [
    RRWebEventSource.MouseMove,
    RRWebEventSource.MouseInteraction,
    RRWebEventSource.Scroll,
    RRWebEventSource.ViewportResize,
    RRWebEventSource.Input,
    RRWebEventSource.TouchMove,
    RRWebEventSource.MediaInteraction,
    RRWebEventSource.Drag,
]

ACTIVITY_THRESHOLD_MS = 5000


@dataclass
class V2SegmentationEvent:
    """Simplified event with just the essential information for activity tracking"""

    timestamp: int
    is_active: bool


@dataclass
class V2RecordingSegment:
    """Represents a segment of recording with activity information"""

    kind: str  # 'window' | 'buffer' | 'gap'
    start_timestamp: int  # Epoch time that the segment starts
    end_timestamp: int  # Epoch time that the segment ends
    duration_ms: int
    is_active: bool


@dataclass
class V1RecordingSegment:
    """V1 implementation of recording segment"""

    kind: str  # 'window' | 'buffer' | 'gap'
    start_timestamp: int
    end_timestamp: int
    duration_ms: int
    is_active: bool


def is_v1_active_event(event: dict[str, Any]) -> bool:
    """V1 implementation of active event check"""
    return event.get("type") == 3 and (event.get("data", {}).get("source", -1) in V1_ACTIVE_SOURCES)


def is_v2_active_event(event: dict[str, Any]) -> bool:
    """V2 implementation of active event check"""
    event_type = event.get("type")
    data = event.get("data")
    source = data.get("source") if isinstance(data, dict) else None

    return event_type == RRWebEventType.IncrementalSnapshot and source in V2_ACTIVE_SOURCES


def to_v2_segmentation_event(event: dict[str, Any]) -> V2SegmentationEvent:
    """Converts an RRWeb event to a simplified V2SegmentationEvent"""
    data = event.get("data", {})
    if not isinstance(data, dict) or "timestamp" not in data:
        raise ValueError("Invalid event data - missing timestamp")
    return V2SegmentationEvent(timestamp=data["timestamp"], is_active=is_v2_active_event(event["data"]))


def create_v1_segments(snapshots: list[dict[str, Any]]) -> list[V1RecordingSegment]:
    """V1 implementation of segment creation"""
    segments: list[V1RecordingSegment] = []
    active_segment: Optional[V1RecordingSegment] = None
    last_active_event_timestamp = 0

    for snapshot in snapshots:
        event_is_active = is_v1_active_event(snapshot["data"])
        if not isinstance(snapshot.get("data"), dict) or "timestamp" not in snapshot["data"]:
            continue
        timestamp = snapshot["data"]["timestamp"]

        # When do we create a new segment?
        # 1. If we don't have one yet
        is_new_segment = active_segment is None

        # 2. If it is currently inactive but a new "active" event comes in
        if event_is_active and not (active_segment and active_segment.is_active):
            is_new_segment = True

        # 3. If it is currently active but no new active event has been seen for the activity threshold
        if (
            active_segment
            and active_segment.is_active
            and last_active_event_timestamp + ACTIVITY_THRESHOLD_MS < timestamp
        ):
            is_new_segment = True

        # NOTE: We have to make sure that we set this _after_ we use it
        last_active_event_timestamp = timestamp if event_is_active else last_active_event_timestamp

        if is_new_segment:
            if active_segment:
                segments.append(active_segment)

            active_segment = V1RecordingSegment(
                kind="window",
                start_timestamp=timestamp,
                end_timestamp=timestamp,
                duration_ms=0,
                is_active=event_is_active,
            )
        elif active_segment:
            active_segment.end_timestamp = timestamp
            active_segment.duration_ms = active_segment.end_timestamp - active_segment.start_timestamp

    if active_segment:
        segments.append(active_segment)

    return segments


def create_v2_segments_from_events(segmentation_events: list[V2SegmentationEvent]) -> list[V2RecordingSegment]:
    """V2 implementation of segment creation"""
    sorted_events = sorted(segmentation_events, key=lambda x: x.timestamp)
    segments: list[V2RecordingSegment] = []
    active_segment: Optional[V2RecordingSegment] = None
    last_active_event_timestamp = 0

    for event in sorted_events:
        # When do we create a new segment?
        # 1. If we don't have one yet
        is_new_segment = active_segment is None

        # 2. If it is currently inactive but a new "active" event comes in
        if event.is_active and not (active_segment and active_segment.is_active):
            is_new_segment = True

        # 3. If it is currently active but no new active event has been seen for the activity threshold
        if (
            active_segment
            and active_segment.is_active
            and last_active_event_timestamp + ACTIVITY_THRESHOLD_MS < event.timestamp
        ):
            is_new_segment = True

        # NOTE: We have to make sure that we set this _after_ we use it
        if event.is_active:
            last_active_event_timestamp = event.timestamp

        if is_new_segment:
            if active_segment:
                segments.append(active_segment)

            active_segment = V2RecordingSegment(
                kind="window",
                start_timestamp=event.timestamp,
                end_timestamp=event.timestamp,
                duration_ms=0,
                is_active=event.is_active,
            )
        elif active_segment:
            active_segment.end_timestamp = event.timestamp
            active_segment.duration_ms = active_segment.end_timestamp - active_segment.start_timestamp

    if active_segment:
        segments.append(active_segment)

    return segments


def v2_active_milliseconds_from_events(segmentation_events: list[V2SegmentationEvent]) -> int:
    """V2 implementation: Calculates the total active time in milliseconds from a list of segmentation events"""
    segments = create_v2_segments_from_events(segmentation_events)
    return v2_active_milliseconds_from_segments(segments)


def v2_active_milliseconds_from_segments(segments: list[V2RecordingSegment]) -> int:
    """V2 implementation: Calculates total active milliseconds from segments"""
    return sum(max(1, segment.duration_ms) if segment.is_active else 0 for segment in segments)


def v1_active_milliseconds(snapshots: list[dict[str, Any]]) -> int:
    """V1 implementation: Compute active milliseconds from a list of snapshots"""
    segments = create_v1_segments(snapshots)
    return sum(max(1, segment.duration_ms) if segment.is_active else 0 for segment in segments)


def v2_active_milliseconds(snapshots: list[dict[str, Any]]) -> int:
    """V2 implementation: Compute active milliseconds from a list of snapshots"""
    segmentation_events = [to_v2_segmentation_event(event) for event in snapshots]
    return v2_active_milliseconds_from_events(segmentation_events)


def compute_active_milliseconds(snapshots: list[dict[str, Any]]) -> tuple[int, int]:
    """Compute active milliseconds using both v1 and v2 implementations"""
    v1_ms = v1_active_milliseconds(snapshots)
    v2_ms = v2_active_milliseconds(snapshots)
    return v1_ms, v2_ms
