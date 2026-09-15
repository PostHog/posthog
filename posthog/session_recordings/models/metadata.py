from datetime import UTC, datetime
from typing import Literal, Optional, TypedDict, Union

SnapshotData = dict
WindowId = Optional[str]

# A session counts as ongoing when replay data for it was last ingested within this window.
# Shared so the listing query and the single-recording metadata query agree on "ongoing".
ONGOING_SESSION_WINDOW_MINUTES = 5


def as_utc(timestamp: datetime) -> datetime:
    """Replay queries derive `expiry_time` in SQL from `dateTrunc` plus an interval, and ClickHouse
    can return such a computed value with no timezone. The value is always UTC, so attach it here.
    Otherwise the naive result raises TypeError when it is compared against an aware `now`."""
    return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)


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
    snapshot_library: Optional[str]
    block_first_timestamps: list[datetime]
    block_last_timestamps: list[datetime]
    block_urls: list[str]
    retention_period_days: Optional[int]
    expiry_time: datetime
    recording_ttl: int
    ongoing: bool
    total_size: int
    event_count: int


class RecordingMatchingEvents(TypedDict):
    events: list[MatchingSessionRecordingEvent]
