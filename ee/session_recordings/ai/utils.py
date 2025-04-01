import dataclasses
from datetime import datetime

import hashlib
from typing import Any
import uuid


@dataclasses.dataclass(frozen=True)
class SessionSummaryMetadata:
    id: str
    active_seconds: int | None
    inactive_seconds: int | None
    start_time: datetime | None
    end_time: datetime | None
    click_count: int | None
    keypress_count: int | None
    mouse_activity_count: int | None
    console_log_count: int | None
    console_warn_count: int | None
    console_error_count: int | None
    start_url: str | None
    activity_score: float | None

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        # Convert datetime to ISO format
        if self.start_time:
            d["start_time"] = self.start_time.isoformat()
        if self.end_time:
            d["end_time"] = self.end_time.isoformat()
        return d

    def __json__(self):
        return self.to_dict()


@dataclasses.dataclass
class SessionSummaryPromptData:
    # We may allow customisation of columns included in the future, and we alter the columns present
    # as we process the data, so want to stay as loose as possible here
    columns: list[str] = dataclasses.field(default_factory=list)
    results: list[list[Any]] = dataclasses.field(default_factory=list)
    metadata: SessionSummaryMetadata | None = None
    # In order to reduce the number of tokens in the prompt,
    # we generate mappings to use in the prompt instead of repeating the data
    window_id_mapping: dict[str, int] = dataclasses.field(default_factory=dict)
    url_mapping: dict[str, str] = dataclasses.field(default_factory=dict)

    # one for each result in results
    processed_elements_chain: list[dict] = dataclasses.field(default_factory=list)

    def _get_column_index(self, column_name: str) -> int | None:
        for i, c in enumerate(self.columns):
            if c == column_name:
                return i
        return None

    def populate_through_session_data(
        self, raw_session_events: list[list[Any]], raw_session_metadata: dict[str, Any], columns: list[str]
    ) -> None:
        if not raw_session_events or not raw_session_metadata:
            return
        self.columns = [*columns, "event_id"]
        self.metadata = self._prepare_metadata(raw_session_metadata)
        simplified_session_events: list[list[Any]] = []
        event_hexes = set()
        # Pick indexes as we iterate over arrays
        window_id_index = self._get_column_index("$window_id", columns)
        url_index = self._get_column_index("$current_url", columns)
        timestamp_index = self._get_column_index("timestamp", columns)
        # Iterate session events once to decrease the number of tokens in the prompt through mappings
        for event in raw_session_events:
            # Copy the event to avoid mutating the original
            simplified_event = list(event)
            # Simplify Window IDs
            if window_id_index is not None:
                simplified_event["$window_id"] = self._simplify_window_id(event[window_id_index])
            # Simplify URLs
            if url_index is not None:
                simplified_event["$current_url"] = self._simplify_url(event[url_index])
            # simplified_session_events.append(simplified_event)
            # Calculate time since start to jump to the right place in the player
            if timestamp_index is not None:
                simplified_event["milliseconds_since_start"] = self._calculate_time_since_start(
                    event[timestamp_index], self.metadata.start_time
                )
                # Remove timestamp as we don't need it anymore
                del simplified_event[timestamp_index]
            # Generate a hex for each event to make sure we can identify repeated events.
            event_hex = self._get_deterministic_hex(simplified_event)
            if event_hex in event_hexes:
                # Skip repeated events
                continue
            event_hexes.add(event_hex)
            # Generate a unique id for each event, after hexing (as event id will be unique)
            simplified_event["event_id"] = uuid.uuid4().hex[:8]
        return simplified_session_events

    def _prepare_metadata(self, raw_session_metadata: dict[str, Any]) -> SessionSummaryMetadata:
        # Remove excessive data
        for ef in ("distinct_id", "viewed", "recording_duration", "storage", "ongoing"):
            if ef not in raw_session_metadata:
                continue
            del raw_session_metadata[ef]
        # Adjust the format of the time fields
        start_time = self._prepare_datetime(raw_session_metadata.get("start_time"))
        end_time = self._prepare_datetime(raw_session_metadata.get("end_time"))
        return SessionSummaryMetadata(
            id=raw_session_metadata["id"],  # Expect id to always be present
            active_seconds=raw_session_metadata.get("active_seconds"),
            inactive_seconds=raw_session_metadata.get("inactive_seconds"),
            start_time=start_time,
            end_time=end_time,
            click_count=raw_session_metadata.get("click_count"),
            keypress_count=raw_session_metadata.get("keypress_count"),
            mouse_activity_count=raw_session_metadata.get("mouse_activity_count"),
            console_log_count=raw_session_metadata.get("console_log_count"),
            console_warn_count=raw_session_metadata.get("console_warn_count"),
            console_error_count=raw_session_metadata.get("console_error_count"),
            start_url=raw_session_metadata.get("start_url"),
            activity_score=raw_session_metadata.get("activity_score"),
        )

    def _simplify_window_id(self, window_id: str | None) -> str | None:
        if not window_id:
            return None
        if window_id not in self.window_id_mapping:
            self.window_id_mapping[window_id] = f"window_{len(self.window_id_mapping) + 1}"
        return self.window_id_mapping[window_id]

    def _simplify_url(self, url: str | None) -> str | None:
        if not url:
            return None
        if url not in self.url_mapping:
            self.url_mapping[url] = f"url_{len(self.url_mapping) + 1}"
        return self.url_mapping[url]

    @staticmethod
    def _prepare_datetime(raw_time: datetime | str | None) -> datetime | None:
        if not raw_time:
            return None
        if isinstance(raw_time, str):
            return datetime.fromisoformat(raw_time)
        return raw_time

    @staticmethod
    def _calculate_time_since_start(session_timestamp: str, session_start_time: datetime | None) -> str:
        if not session_start_time or not session_timestamp:
            return None, None
        timestamp_datetime = datetime.fromisoformat(session_timestamp)
        return timestamp_datetime, int((timestamp_datetime - session_start_time).total_seconds() * 1000)

    @staticmethod
    def _get_deterministic_hex(event: list[Any], length: int = 8) -> str:
        """
        Generate a hex for each event to make sure we can identify repeated events.
        """

        def format_value(val: Any) -> str:
            if isinstance(val, datetime):
                return val.isoformat()
            return str(val)

        # Join with a null byte as delimiter since it won't appear in normal strings
        event_string = "\0".join(format_value(x) for x in event)
        return hashlib.sha256(event_string.encode()).hexdigest()[:length]
