import dataclasses
from datetime import datetime

import hashlib
from typing import Any
from urllib.parse import urlparse


@dataclasses.dataclass(frozen=True)
class SessionSummaryMetadata:
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
        if self.start_time:
            d["start_time"] = self.start_time.isoformat()
        if self.end_time:
            d["end_time"] = self.end_time.isoformat()
        return d


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

    def load_session_data(
        self, raw_session_events: list[list[Any]], raw_session_metadata: dict[str, Any], raw_session_columns: list[str]
    ) -> dict[str, list[Any]]:
        """
        Create session summary prompt data from session data, and return a mapping of event ids to events
        to combine events data with the LLM output (avoid LLM returning/hallucinating the event data in the output).
        """
        if not raw_session_events or not raw_session_metadata:
            return
        self.columns = [*raw_session_columns, "milliseconds_since_start", "event_id"]
        self.metadata = self._prepare_metadata(raw_session_metadata)
        events_mapping: dict[str, list[Any]] = {}
        # Pick indexes as we iterate over arrays
        window_id_index = self._get_column_index("$window_id")
        current_url_index = self._get_column_index("$current_url")
        timestamp_index = self._get_column_index("timestamp")
        ms_since_start_index = len(self.columns) - 2
        event_id_index = len(self.columns) - 1
        # Iterate session events once to decrease the number of tokens in the prompt through mappings
        for event in raw_session_events:
            # Copy the event to avoid mutating the original
            simplified_event = [*list(event), None, None]
            # Simplify Window IDs
            if window_id_index is not None:
                simplified_event[window_id_index] = self._simplify_window_id(event[window_id_index])
            # Simplify URLs
            if current_url_index is not None:
                simplified_event[current_url_index] = self._simplify_url(event[current_url_index])
            # Calculate time since start to jump to the right place in the player
            if timestamp_index is not None:
                simplified_event[ms_since_start_index] = self._calculate_time_since_start(
                    event[timestamp_index], self.metadata.start_time
                )
            # Generate a hex for each event to make sure we can identify repeated events, and identify the event
            event_id = self._get_deterministic_hex(simplified_event)
            if event_id in events_mapping:
                # Skip repeated events
                continue
            simplified_event[event_id_index] = event_id
            # Remove timestamp as we don't need it anymore
            del simplified_event[timestamp_index]
            events_mapping[event_id] = simplified_event
        # Remove timestamp column (as we don't store timestamps)
        del self.columns[timestamp_index]
        self.results = list(events_mapping.values())
        return events_mapping

    def _prepare_metadata(self, raw_session_metadata: dict[str, Any]) -> SessionSummaryMetadata:
        # Remove excessive data
        for ef in ("distinct_id", "viewed", "recording_duration", "storage", "ongoing"):
            if ef not in raw_session_metadata:
                continue
            del raw_session_metadata[ef]
        start_time = self._prepare_datetime(raw_session_metadata.get("start_time"))
        end_time = self._prepare_datetime(raw_session_metadata.get("end_time"))
        return SessionSummaryMetadata(
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

    def _get_column_index(self, column_name: str) -> int | None:
        for i, c in enumerate(self.columns):
            if c == column_name:
                return i
        return None

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
            return None
        timestamp_datetime = datetime.fromisoformat(session_timestamp)
        return int((timestamp_datetime - session_start_time).total_seconds() * 1000)

    @staticmethod
    def _get_deterministic_hex(event: list[Any], length: int = 8) -> str:
        """
        Generate a hex for each event to make sure we can identify repeated events.
        """

        def format_value(val: Any) -> str:
            if isinstance(val, datetime):
                return val.isoformat()
            return str(val)

        # Join with a null byte as delimiter since it won't appear in normal strings,
        # so we can the same string using the same combination of values only.
        event_string = "\0".join(format_value(x) for x in event)
        return hashlib.sha256(event_string.encode()).hexdigest()[:length]


def shorten_url(url: str, max_length: int = 256) -> str:
    """
    Shorten long URLs to a more readable length, trying to keep the context.
    """
    if len(url) <= max_length:
        return url
    parsed = urlparse(url)
    # If it's just a long path - keep it and return as is
    if not parsed.query and not parsed.fragment:
        return url
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    # Calculate how many chars we can keep from query
    # Subtract "..." length that we'll add between parts
    remaining_length = max_length - len(base_url) - 3
    # If query is the longer part
    if parsed.query and len(parsed.query) > len(parsed.fragment):
        query_start = parsed.query[: remaining_length // 2]
        query_end = parsed.query[-remaining_length // 2 :]
        return f"{base_url}?{query_start}...{query_end}"
    # If fragment is the longer part
    if parsed.fragment and len(parsed.fragment) > len(parsed.query):
        fragment_start = parsed.fragment[: remaining_length // 2]
        fragment_end = parsed.fragment[-remaining_length // 2 :]
        return f"{base_url}#{fragment_start}...{fragment_end}"
    # If unclear - return the base URL
    return f"{base_url}"
