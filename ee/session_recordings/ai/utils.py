import dataclasses
from datetime import datetime

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
        self, raw_session_events: list[Any], raw_session_metadata: dict[str, Any], columns: list[str]
    ) -> None:
        if not raw_session_events or not raw_session_metadata:
            return
        self.columns = [*columns, "event_id"]
        self.metadata = self._prepare_metadata(raw_session_metadata)
        simplified_session_events = []
        # Pick indexes as we iterate over tuples
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
            simplified_session_events.append(simplified_event)
            # Calculate time since start to jump to the right place in the player
            if timestamp_index is not None:
                simplified_event["milliseconds_since_start"] = self._format_date(
                    event[timestamp_index], self.metadata.start_time
                )
                # Remove timestamp as we don't need it anymore
                del simplified_event[timestamp_index]
            # Each event needs a unique id to link them properly
            simplified_event["event_id"] = uuid.uuid4().hex[:8]
        return simplified_session_events

    def _prepare_metadata(self, raw_session_metadata: dict[str, Any]) -> SessionSummaryMetadata:
        # Remove excessive data
        for ef in ("distinct_id", "viewed", "recording_duration", "storage", "ongoing"):
            if ef not in raw_session_metadata:
                continue
            del raw_session_metadata[ef]
        # Adjust the format of the time fields
        start_time = self._prepare_time(raw_session_metadata.get("start_time"))
        end_time = self._prepare_time(raw_session_metadata.get("end_time"))
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

    def _prepare_time(self, raw_time: datetime | str | None) -> datetime | None:
        if not raw_time:
            return None
        if isinstance(raw_time, str):
            return datetime.fromisoformat(raw_time)
        return raw_time

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

    def _format_date(self, session_timestamp: str, session_start_time: datetime | None) -> str:
        if not session_start_time or not session_timestamp:
            return None, None
        timestamp_datetime = datetime.fromisoformat(session_timestamp)
        return timestamp_datetime, int((timestamp_datetime - session_start_time).total_seconds() * 1000)


def collapse_sequence_of_events(session_events: SessionSummaryPromptData) -> SessionSummaryPromptData:
    # assumes the list is ordered by timestamp
    if session_events.is_empty():
        return session_events

    # find the event column index
    event_index = session_events.column_index("event")

    # find the window id column index
    window_id_index = session_events.column_index("$window_id")

    event_repetition_count_index: int | None = None
    # we only append this new column, if we need to add it below

    # now enumerate the results finding sequences of events with the same event and collapsing them to a single item
    collapsed_results = []
    for i, result in enumerate(session_events.results):
        if event_index is None:
            collapsed_results.append(result)
            continue

        event: str | None = result[event_index]
        if not event:
            collapsed_results.append(result)
            continue

        if i == 0:
            collapsed_results.append(result)
            continue

        # we need to collapse into the last item added into collapsed results
        # as we're going to amend it in place
        previous_result = collapsed_results[len(collapsed_results) - 1]
        previous_event: str | None = previous_result[event_index]
        if not previous_event:
            collapsed_results.append(result)
            continue

        event_matches = previous_event == event
        window_matches = previous_result[window_id_index] == result[window_id_index] if window_id_index else True

        if event_matches and window_matches:
            # collapse the event into the previous result
            if event_repetition_count_index is None:
                # we need to add the column
                event_repetition_count_index = len(session_events.columns)
                session_events.columns.append("event_repetition_count")
            previous_result_list = list(previous_result)
            try:
                existing_repetition_count = previous_result_list[event_repetition_count_index] or 0
                previous_result_list[event_repetition_count_index] = existing_repetition_count + 1
            except IndexError:
                previous_result_list.append(2)

            collapsed_results[len(collapsed_results) - 1] = previous_result_list
        else:
            result.append(None)  # there is no event repetition count
            collapsed_results.append(result)

    return dataclasses.replace(session_events, results=collapsed_results)
