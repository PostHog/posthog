import dataclasses
from datetime import datetime
from typing import Literal, Optional, TypedDict, Union

SnapshotData = dict
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
    data: dict[str, Union[int, str]]


# NOTE: MatchingSessionRecordingEvent is a minimal version of full events that is used to display events matching a filter on the frontend
class MatchingSessionRecordingEvent(TypedDict):
    uuid: str
    timestamp: datetime
    session_id: str
    window_id: str


class DecompressedRecordingData(TypedDict):
    has_next: bool
    snapshot_data_by_window_id: dict[WindowId, list[Union[SnapshotData, SessionRecordingEventSummary]]]


@dataclasses.dataclass(frozen=True)
class RecordingBlockListing:
    start_time: datetime
    block_first_timestamps: list[datetime]
    block_last_timestamps: list[datetime]
    block_urls: list[str]

    def is_empty(self) -> bool:
        return not self.block_urls


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
    snapshot_source: Literal["web", "mobile"]
    block_first_timestamps: list[datetime]
    block_last_timestamps: list[datetime]
    block_urls: list[str]
    retention_period_days: Optional[int]


class RecordingMatchingEvents(TypedDict):
    events: list[MatchingSessionRecordingEvent]
