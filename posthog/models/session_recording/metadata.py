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


# NOTE: MatchingSessionRecordingEvent is a minimal version of full events that is used to display events matching a filter on the frontend
class MatchingSessionRecordingEvent(TypedDict):
    uuid: str
    timestamp: datetime
    session_id: str
    window_id: str


class DecompressedRecordingData(TypedDict):
    has_next: bool
    snapshot_data_by_window_id: Dict[WindowId, List[Union[SnapshotData, SessionRecordingEventSummary]]]


class RecordingMetadata(TypedDict):
    distinct_id: str
    segments: List[RecordingSegment]
    start_and_end_times_by_window_id: Dict[WindowId, RecordingSegment]
    start_time: datetime
    end_time: datetime
    click_count: int
    keypress_count: int
    urls: List[str]
    duration: int


class RecordingMatchingEvents(TypedDict):
    events: List[MatchingSessionRecordingEvent]


class PersistedRecordingV1(TypedDict):
    version: str  # "2022-12-22"
    snapshot_data_by_window_id: Dict[WindowId, List[Union[SnapshotData, SessionRecordingEventSummary]]]
    distinct_id: str
    segments: List[RecordingSegment]
    start_and_end_times_by_window_id: Dict[WindowId, RecordingSegment]
