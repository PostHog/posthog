from datetime import datetime

from typing import List, Dict, Tuple

import openai
from prometheus_client import Histogram

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
        float("inf"),
    ],
)


def reduce_elements_chain(session_events: Tuple[List | None, List | None]) -> Tuple[List | None, List | None]:
    columns, results = session_events

    if columns is None or results is None:
        return columns, results

    # find elements_chain column index
    elements_chain_index = None
    for i, column in enumerate(columns):
        if column == "elements_chain":
            elements_chain_index = i
            break

    reduced_results = []
    for result in results:
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
        reduced_results.append(tuple(result_list))

    return columns, reduced_results


def simplify_window_id(session_events: Tuple[List | None, List | None]) -> Tuple[List | None, List | None]:
    columns, results = session_events

    if columns is None or results is None:
        return columns, results

    # find window_id column index
    window_id_index = None
    for i, column in enumerate(columns):
        if column == "$window_id":
            window_id_index = i
            break

    window_id_mapping: Dict[str, int] = {}
    simplified_results = []
    for result in results:
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
        simplified_results.append(tuple(result_list))

    return columns, simplified_results


def deduplicate_urls(
    session_events: Tuple[List | None, List | None]
) -> Tuple[List | None, List | None, Dict[str, str]]:
    columns, results = session_events

    if columns is None or results is None:
        return columns, results, {}

    # find url column index
    url_index = None
    for i, column in enumerate(columns):
        if column == "$current_url":
            url_index = i
            break

    url_mapping: Dict[str, str] = {}
    deduplicated_results = []
    for result in results:
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
        deduplicated_results.append(tuple(result_list))

    return columns, deduplicated_results, url_mapping


def format_dates(session_events: Tuple[List | None, List | None], start: datetime) -> Tuple[List | None, List | None]:
    columns, results = session_events

    if columns is None or results is None:
        return columns, results

    # find timestamp column index
    timestamp_index = None
    for i, column in enumerate(columns):
        if column == "timestamp":
            timestamp_index = i
            break

    if timestamp_index is None:
        # no timestamp column so nothing to do
        return columns, results

    del columns[timestamp_index]  # remove timestamp column from columns
    columns.append("milliseconds_since_start")  # add new column to columns at end

    formatted_results = []
    for result in results:
        timestamp: datetime | None = result[timestamp_index]
        if not timestamp:
            formatted_results.append(result)
            continue

        result_list = list(result)
        # remove list item at timestamp_index
        del result_list[timestamp_index]
        # insert milliseconds since reference date
        result_list.append(int((timestamp - start).total_seconds() * 1000))
        formatted_results.append(tuple(result_list))

    return columns, formatted_results


def collapse_sequence_of_events(session_events: Tuple[List | None, List | None]) -> Tuple[List | None, List | None]:
    # assumes the list is ordered by timestamp
    columns, results = session_events

    if columns is None or results is None:
        return columns, results

    # find the event column index
    event_index = None
    for i, column in enumerate(columns):
        if column == "event":
            event_index = i
            break

    # now enumerate the results finding sequences of events with the same event and collapsing them to a single item
    collapsed_results = []
    for i, result in enumerate(results):
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

        previous_result = results[i - 1]
        previous_event: str | None = previous_result[event_index]
        if not previous_event:
            collapsed_results.append(result)
            continue

        if previous_event == event:
            # collapse the event into the previous result
            collapsed_results[-1] = tuple(
                [
                    previous_result[j] if j != event_index else f"{previous_event} x 2"
                    for j in range(len(previous_result))
                ]
            )
        else:
            collapsed_results.append(result)

    return columns, collapsed_results


def summarize_recording(recording: SessionRecording, user: User, team: Team):
    session_metadata = SessionReplayEvents().get_metadata(session_id=str(recording.session_id), team=team)
    if not session_metadata:
        raise ValueError(f"no session metadata found for session_id {recording.session_id}")

    session_events = SessionReplayEvents().get_events(
        session_id=str(recording.session_id),
        team=team,
        metadata=session_metadata,
        events_to_ignore=[
            "$feature_flag_called",
        ],
    )

    # convert session_metadata to a Dict from a TypedDict
    # so that we can amend its values freely
    session_metadata_dict = dict(session_metadata)

    del session_metadata_dict["distinct_id"]
    start_time = session_metadata["start_time"]
    session_metadata_dict["start_time"] = start_time.isoformat()
    session_metadata_dict["end_time"] = session_metadata["end_time"].isoformat()

    session_events_columns, session_events_results, url_mapping = deduplicate_urls(
        collapse_sequence_of_events(
            format_dates(reduce_elements_chain(simplify_window_id(session_events)), start=start_time)
        )
    )

    instance_region = get_instance_region() or "HOBBY"
    messages = [
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
            URLs associated with the events can be found in this mapping {url_mapping}.
            """,
        },
        {
            "role": "user",
            "content": f"""the session events I have are {session_events_results}.
            with columns {session_events_columns}.
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
    ]
    result = openai.ChatCompletion.create(
        # model="gpt-4-1106-preview",  # allows 128k tokens
        model="gpt-4",  # allows 8k tokens
        temperature=0.7,
        messages=messages,
        user=f"{instance_region}/{user.pk}",  # The user ID is for tracking within OpenAI in case of overuse/abuse
    )

    usage = result.get("usage", {}).get("prompt_tokens", None)
    if usage:
        TOKENS_IN_PROMPT_HISTOGRAM.observe(usage)

    content: str = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"ai_result": result, "content": content, "prompt": messages}
