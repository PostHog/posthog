import dataclasses
from datetime import datetime

from typing import List, Dict, Any

from openai import OpenAI

from prometheus_client import Histogram

from posthog.api.activity_log import ServerTimingsGathered
from posthog.models import User, Team
from posthog.models.element import chain_to_elements
from posthog.session_recordings.models.session_recording import SessionRecording

from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from posthog.utils import get_instance_region

TOKENS_IN_PROMPT_HISTOGRAM = Histogram(
    "posthog_session_summary_tokens_in_prompt_histogram",
    "histogram of the number of tokens in the prompt used to generate a session summary",
    buckets=[
        0,
        10,
        50,
        100,
        500,
        1000,
        2000,
        3000,
        4000,
        5000,
        6000,
        7000,
        8000,
        10000,
        20000,
        30000,
        40000,
        50000,
        100000,
        128000,
        float("inf"),
    ],
)


@dataclasses.dataclass
class SessionSummaryPromptData:
    # we may allow customisation of columns included in the future,
    # and we alter the columns present as we process the data
    # so want to stay as loose as possible here
    columns: List[str] = dataclasses.field(default_factory=list)
    results: List[List[Any]] = dataclasses.field(default_factory=list)
    # in order to reduce the number of tokens in the prompt
    # we replace URLs with a placeholder and then pass this mapping of placeholder to URL into the prompt
    url_mapping: Dict[str, str] = dataclasses.field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.columns or not self.results

    def column_index(self, column: str) -> int | None:
        for i, c in enumerate(self.columns):
            if c == column:
                return i
        return None


def reduce_elements_chain(session_events: SessionSummaryPromptData) -> SessionSummaryPromptData:
    if session_events.is_empty():
        return session_events

    # find elements_chain column index
    elements_chain_index = session_events.column_index("elements_chain")

    reduced_results = []
    for result in session_events.results:
        if elements_chain_index is None:
            reduced_results.append(result)
            continue

        elements_chain: str | None = result[elements_chain_index]
        if not elements_chain:
            reduced_results.append(result)
            continue

        # the elements chain has lots of information that we don't need
        elements = [e for e in chain_to_elements(elements_chain) if e.tag_name in e.USEFUL_ELEMENTS]

        result_list = list(result)
        result_list[elements_chain_index] = [{"tag": e.tag_name, "text": e.text, "href": e.href} for e in elements]
        reduced_results.append(result_list)

    return dataclasses.replace(session_events, results=reduced_results)


def simplify_window_id(session_events: SessionSummaryPromptData) -> SessionSummaryPromptData:
    if session_events.is_empty():
        return session_events

    # find window_id column index
    window_id_index = session_events.column_index("$window_id")

    window_id_mapping: Dict[str, int] = {}
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


def deduplicate_urls(session_events: SessionSummaryPromptData) -> SessionSummaryPromptData:
    if session_events.is_empty():
        return session_events

    # find url column index
    url_index = session_events.column_index("$current_url")

    url_mapping: Dict[str, str] = {}
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


def summarize_recording(recording: SessionRecording, user: User, team: Team):
    timer = ServerTimingsGathered()

    with timer("get_metadata"):
        session_metadata = SessionReplayEvents().get_metadata(session_id=str(recording.session_id), team=team)
        if not session_metadata:
            raise ValueError(f"no session metadata found for session_id {recording.session_id}")

    with timer("get_events"):
        session_events = SessionReplayEvents().get_events(
            session_id=str(recording.session_id),
            team=team,
            metadata=session_metadata,
            events_to_ignore=[
                "$feature_flag_called",
            ],
        )
        if not session_events or not session_events[0] or not session_events[1]:
            raise ValueError(f"no events found for session_id {recording.session_id}")

    # convert session_metadata to a Dict from a TypedDict
    # so that we can amend its values freely
    session_metadata_dict = dict(session_metadata)

    del session_metadata_dict["distinct_id"]
    start_time = session_metadata["start_time"]
    session_metadata_dict["start_time"] = start_time.isoformat()
    session_metadata_dict["end_time"] = session_metadata["end_time"].isoformat()

    with timer("generate_prompt"):
        prompt_data = deduplicate_urls(
            collapse_sequence_of_events(
                format_dates(
                    reduce_elements_chain(
                        simplify_window_id(
                            SessionSummaryPromptData(columns=session_events[0], results=session_events[1])
                        )
                    ),
                    start=start_time,
                )
            )
        )

    instance_region = get_instance_region() or "HOBBY"

    with timer("openai_completion"):
        result = OpenAI().chat.completions.create(
            # model="gpt-4-1106-preview",  # allows 128k tokens
            model="gpt-4",  # allows 8k tokens
            temperature=0.7,
            messages=[
                {
                    "role": "system",
                    "content": """
            Session Replay is PostHog's tool to record visits to web sites and apps.
            We also gather events that occur like mouse clicks and key presses.
            You write two or three sentence concise and simple summaries of those sessions based on a prompt.
            You are more likely to mention errors or things that look like business success such as checkout events.
            You don't help with other knowledge.""",
                },
                {
                    "role": "user",
                    "content": f"""the session metadata I have is {session_metadata_dict}.
            it gives an overview of activity and duration""",
                },
                {
                    "role": "user",
                    "content": f"""
            URLs associated with the events can be found in this mapping {prompt_data.url_mapping}.
            """,
                },
                {
                    "role": "user",
                    "content": f"""the session events I have are {prompt_data.results}.
            with columns {prompt_data.columns}.
            they give an idea of what happened and when,
            if present the elements_chain extracted from the html can aid in understanding
            but should not be directly used in your response""",
                },
                {
                    "role": "user",
                    "content": """
            generate a two or three sentence summary of the session.
            use as concise and simple language as is possible.
            assume a reading age of around 12 years old.
            generate no text other than the summary.""",
                },
            ],
            user=f"{instance_region}/{user.pk}",  # allows 8k tokens
        )

        usage = result.usage.prompt_tokens if result.usage else None
        if usage:
            TOKENS_IN_PROMPT_HISTOGRAM.observe(usage)

    content: str = result.choices[0].message.content or ""
    return {"content": content, "timings": timer.get_all_timings()}
