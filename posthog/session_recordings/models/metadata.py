from datetime import datetime
from typing import Dict, List, Optional, TypedDict, Union

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
    start_time: datetime
    end_time: datetime
    click_count: int
    keypress_count: int
    mouse_activity_count: int
    console_log_count: int
    console_warn_count: int
    console_error_count: int
    first_url: str
    duration: int
    active_seconds: int


class RecordingMatchingEvents(TypedDict):
    events: List[MatchingSessionRecordingEvent]


class PersistedRecordingV1(TypedDict):
    version: str  # "2022-12-22"
    snapshot_data_by_window_id: Dict[WindowId, List[Union[SnapshotData, SessionRecordingEventSummary]]]
    distinct_id: str
