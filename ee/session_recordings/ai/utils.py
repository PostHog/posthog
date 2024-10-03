import dataclasses
from datetime import datetime

from typing import Any

from hashlib import shake_256


@dataclasses.dataclass
class SessionSummaryPromptData:
    # we may allow customisation of columns included in the future,
    # and we alter the columns present as we process the data
    # so want to stay as loose as possible here
    columns: list[str] = dataclasses.field(default_factory=list)
    results: list[list[Any]] = dataclasses.field(default_factory=list)
    # in order to reduce the number of tokens in the prompt
    # we replace URLs with a placeholder and then pass this mapping of placeholder to URL into the prompt
    url_mapping: dict[str, str] = dataclasses.field(default_factory=dict)

    # one for each result in results
    processed_elements_chain: list[dict] = dataclasses.field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.columns or not self.results

    def column_index(self, column: str) -> int | None:
        for i, c in enumerate(self.columns):
            if c == column:
                return i
        return None


def simplify_window_id(session_events: SessionSummaryPromptData) -> SessionSummaryPromptData:
    if session_events.is_empty():
        return session_events

    # find window_id column index
    window_id_index = session_events.column_index("$window_id")

    window_id_mapping: dict[str, int] = {}
    simplified_results = []
    for result in session_events.results:
        if window_id_index is None:
            simplified_results.append(result)
            continue

        window_id: str | None = result[window_id_index]
        if not window_id:
            simplified_results.append(result)
            continue

        if window_id not in window_id_mapping:
            window_id_mapping[window_id] = len(window_id_mapping) + 1

        result_list = list(result)
        result_list[window_id_index] = window_id_mapping[window_id]
        simplified_results.append(result_list)

    return dataclasses.replace(session_events, results=simplified_results)


def only_pageview_urls(session_events: SessionSummaryPromptData) -> SessionSummaryPromptData:
    """
    including the url with every event is a lot of duplication,
    so we remove it from all events except pageviews
    """
    if session_events.is_empty():
        return session_events

    # find url column index
    url_index = session_events.column_index("$current_url")
    event_index = session_events.column_index("event")

    pageview_results = []
    for result in session_events.results:
        if url_index is None or event_index is None:
            pageview_results.append(result)
            continue

        url: str | None = result[url_index]
        event: str | None = result[event_index]
        if not url:
            pageview_results.append(result)
            continue
        if event == "$pageview":
            pageview_results.append(result)
            continue

        # otherwise we hash the url, so we have ~one token per event
        # this would mean sessions with multiple events that only
        # differ by URL should still have some distance between them
        result[url_index] = shake_256(url.encode("utf-8")).hexdigest(4)
        pageview_results.append(result)

    return dataclasses.replace(session_events, results=pageview_results)


def deduplicate_urls(session_events: SessionSummaryPromptData) -> SessionSummaryPromptData:
    if session_events.is_empty():
        return session_events

    # find url column index
    url_index = session_events.column_index("$current_url")

    url_mapping: dict[str, str] = {}
    deduplicated_results = []
    for result in session_events.results:
        if url_index is None:
            deduplicated_results.append(result)
            continue

        url: str | None = result[url_index]
        if not url:
            deduplicated_results.append(result)
            continue

        if url not in url_mapping:
            url_mapping[url] = f"url_{len(url_mapping) + 1}"

        result_list = list(result)
        result_list[url_index] = url_mapping[url]
        deduplicated_results.append(result_list)

    return dataclasses.replace(session_events, results=deduplicated_results, url_mapping=url_mapping)


def format_dates(session_events: SessionSummaryPromptData, start: datetime) -> SessionSummaryPromptData:
    if session_events.is_empty():
        return session_events

    # find timestamp column index
    timestamp_index = session_events.column_index("timestamp")

    if timestamp_index is None:
        # no timestamp column so nothing to do
        return session_events

    del session_events.columns[timestamp_index]  # remove timestamp column from columns
    session_events.columns.append("milliseconds_since_start")  # add new column to columns at end

    formatted_results = []
    for result in session_events.results:
        timestamp: datetime | None = result[timestamp_index]
        if not timestamp:
            formatted_results.append(result)
            continue

        result_list = list(result)
        # remove list item at timestamp_index
        del result_list[timestamp_index]
        # insert milliseconds since reference date
        result_list.append(int((timestamp - start).total_seconds() * 1000))
        formatted_results.append(result_list)

    return dataclasses.replace(session_events, results=formatted_results)


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
