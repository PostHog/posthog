from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict, Union

SnapshotData = Dict
WindowId = Optional[str]


class RecordingSegment(TypedDict):
    start_time: datetime
    end_time: datetime
    window_id: WindowId
    is_active: bool


class SnapshotDataTaggedWithWindowId(TypedDict):
    window_id: WindowId
    snapshot_data: SnapshotData


# NOTE: EventSummary is a minimal version of full events, containing only some of the "data" content - strings and numbers
class SessionRecordingEventSummary(TypedDict):
    timestamp: int
    type: int
    # keys of this object should be any of EVENT_SUMMARY_DATA_INCLUSIONS
    data: Dict[str, Union[int, str]]


class SessionRecordingEvent(TypedDict):
    timestamp: datetime
    distinct_id: str
    session_id: str
    window_id: str
    snapshot_data: Dict[str, Any]
    events_summary: List[SessionRecordingEventSummary]


class DecompressedRecordingData(TypedDict):
    has_next: bool
    snapshot_data_by_window_id: Dict[WindowId, List[Union[SnapshotData, SessionRecordingEventSummary]]]


class RecordingMetadata(TypedDict):
    distinct_id: str
    segments: List[RecordingSegment]
    start_and_end_times_by_window_id: Dict[WindowId, RecordingSegment]
