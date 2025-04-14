import dataclasses
from datetime import datetime

import hashlib
from typing import Any

from ee.session_recordings.session_summary.utils import get_column_index, prepare_datetime


@dataclasses.dataclass(frozen=True)
class SessionSummaryMetadata:
    active_seconds: int | None = None
    inactive_seconds: int | None = None
    start_time: datetime | None = None
    click_count: int | None = None
    keypress_count: int | None = None
    mouse_activity_count: int | None = None
    start_url: str | None = None

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        if self.start_time:
            d["start_time"] = self.start_time.isoformat()
        return d


@dataclasses.dataclass
class SessionSummaryPromptData:
    # We may allow customisation of columns included in the future, and we alter the columns present
    # as we process the data, so want to stay as loose as possible here
    columns: list[str] = dataclasses.field(default_factory=list)
    results: list[list[Any]] = dataclasses.field(default_factory=list)
    metadata: SessionSummaryMetadata = dataclasses.field(default_factory=SessionSummaryMetadata)
    # In order to reduce the number of tokens in the prompt,
    # we generate mappings to use in the prompt instead of repeating the data
    window_id_mapping: dict[str, str] = dataclasses.field(default_factory=dict)
    url_mapping: dict[str, str] = dataclasses.field(default_factory=dict)

    def load_session_data(
        self,
        raw_session_events: list[list[Any]],
        raw_session_metadata: dict[str, Any],
        raw_session_columns: list[str],
        session_id: str,
    ) -> dict[str, list[Any]]:
        """
        Create session summary prompt data from session data, and return a mapping of event ids to events
        to combine events data with the LLM output (avoid LLM returning/hallucinating the event data in the output).
        """
        if not raw_session_events:
            raise ValueError(f"No session events provided for summarizing session_id {session_id}")
        if not raw_session_metadata:
            raise ValueError(f"No session metadata provided for summarizing session_id {session_id}")
        self.columns = [*raw_session_columns, "event_id", "event_index"]
        self.metadata = self._prepare_metadata(raw_session_metadata)
        simplified_events_mapping: dict[str, list[Any]] = {}
        # Pick indexes as we iterate over arrays
        window_id_index = get_column_index(self.columns, "$window_id")
        current_url_index = get_column_index(self.columns, "$current_url")
        timestamp_index = get_column_index(self.columns, "timestamp")
        event_id_index = len(self.columns) - 2
        event_index_index = len(self.columns) - 1
        # Iterate session events once to decrease the number of tokens in the prompt through mappings
        for i, event in enumerate(raw_session_events):
            # Copy the event to avoid mutating the original
            simplified_event = [*list(event), None, None]
            # Stringify timestamp to avoid datetime objects in the prompt
            if timestamp_index is not None:
                simplified_event[timestamp_index] = event[timestamp_index].isoformat()
            # Simplify Window IDs
            if window_id_index is not None:
                simplified_event[window_id_index] = self._simplify_window_id(event[window_id_index])
            # Simplify URLs
            if current_url_index is not None:
                simplified_event[current_url_index] = self._simplify_url(event[current_url_index])
            # Generate a hex for each event to make sure we can identify repeated events, and identify the event
            event_id = self._get_deterministic_hex(simplified_event)
            if event_id in simplified_events_mapping:
                # Skip repeated events
                continue
            simplified_event[event_id_index] = event_id
            simplified_event[event_index_index] = i
            simplified_events_mapping[event_id] = simplified_event
        self.results = list(simplified_events_mapping.values())
        return simplified_events_mapping

    def _prepare_metadata(self, raw_session_metadata: dict[str, Any]) -> SessionSummaryMetadata:
        # Remove excessive data or fields that negatively impact the LLM performance
        # For example, listing 114 errors, increases chances of error hallucination
        session_metadata = raw_session_metadata.copy()  # Avoid mutating the original
        allowed_fields = (
            "active_seconds",
            "inactive_seconds",
            "start_time",
            "click_count",
            "keypress_count",
            "mouse_activity_count",
            "start_url",
            "console_errors",
        )
        session_metadata = {k: v for k, v in session_metadata.items() if k in allowed_fields}
        # Start time should be always present
        if "start_time" not in session_metadata:
            raise ValueError(f"start_time is required in session metadata: {session_metadata}")
        start_time = prepare_datetime(session_metadata["start_time"])
        return SessionSummaryMetadata(
            active_seconds=session_metadata.get("active_seconds"),
            inactive_seconds=session_metadata.get("inactive_seconds"),
            start_time=start_time,
            click_count=session_metadata.get("click_count"),
            keypress_count=session_metadata.get("keypress_count"),
            mouse_activity_count=session_metadata.get("mouse_activity_count"),
            start_url=session_metadata.get("start_url"),
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
    def _get_deterministic_hex(event: list[Any], length: int = 8) -> str:
        """
        Generate a hex for each event to make sure we can identify repeated events.
        """

        def format_value(val: Any) -> str:
            if isinstance(val, datetime):
                return val.isoformat()
            return str(val)

        # Join with a null byte as delimiter since it won't appear in normal strings,
        # so we can get the same string using the same combination of values only.
        event_string = "\0".join(format_value(x) for x in event)
        return hashlib.sha256(event_string.encode()).hexdigest()[:length]
