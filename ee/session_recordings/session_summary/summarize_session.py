import openai

from prometheus_client import Histogram

from ee.session_recordings.session_summary.utils import (
    load_session_metadata_from_json,
    load_sesssion_recording_events_from_csv,
)
from posthog.api.activity_log import ServerTimingsGathered
from posthog.models import User, Team
from posthog.session_recordings.models.session_recording import SessionRecording
from django.template.loader import get_template

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


def _get_session_metadata(session_id: str, team: Team) -> dict:
    # TODO: Uncomment after testing with production data
    # session_metadata = SessionReplayEvents().get_metadata(session_id=str(session_id), team=team)
    # if not session_metadata:
    #     raise ValueError(f"no session metadata found for session_id {session_id}")
    # Load session metadata from JSON to load with production data.
    # TODO: Remove before merging, using to test with production data
    session_metadata = load_session_metadata_from_json(
        "/Users/woutut/Documents/Code/posthog/playground/single-session-metadata_0195f10e-7c84-7944-9ea2-0303a4b37af7.json"
    )
    # Convert session_metadata to a dict, so that we can amend its values freely
    session_metadata_dict = dict(session_metadata)
    return session_metadata_dict


def _get_session_events(session_id: str, team: Team) -> list[list[str], list[tuple[str | None, ...]]]:
    # TODO: Uncomment after testing with production data
    # session_events = SessionReplayEvents().get_events(
    #     session_id=str(session_id),
    #     team=team,
    #     metadata=session_metadata,
    #     events_to_ignore=[
    #         "$feature_flag_called",
    #     ],
    # )
    # Load session events from CSV to load with production data.
    # TODO: Remove before merging, using to test with production data
    session_events = load_sesssion_recording_events_from_csv(
        "/Users/woutut/Documents/Code/posthog/playground/single-session-csv-export_0195f10e-7c84-7944-9ea2-0303a4b37af7.csv"
    )
    if not session_events or not session_events[0] or not session_events[1]:
        raise ValueError(f"no events found for session_id {session_id}")
    return session_events[0], session_events[1]


def summarize_recording(recording: SessionRecording, user: User, team: Team):
    timer = ServerTimingsGathered()

    with timer("get_metadata"):
        session_metadata = _get_session_metadata(recording.session_id, team)

    with timer("get_events"):
        session_events_columns, session_events = _get_session_events(recording.session_id, team)

    with timer("generate_prompt"):
        # prompt_data = deduplicate_urls(
        #     collapse_sequence_of_events(
        #         format_dates(
        #             simplify_window_id(SessionSummaryPromptData(columns=session_events[0], results=session_events[1])),
        #             start=start_time,
        #         )
        #     )
        # )
        template = get_template(f"session_summaries/single-replay_base-prompt.md")
        rendered_template = template.render({"EVENTS_DATA": session_events, "SESSION_METADATA": session_metadata})

    instance_region = get_instance_region() or "HOBBY"
    combined_sesssion_events = []
    for event in session_events:
        combined_session = {}
        for index, column in enumerate(session_events_columns):
            try:
                combined_session[column] = event[index]
            except IndexError:
                pass
        combined_sesssion_events.append(combined_session)

    with timer("openai_completion"):
        result = openai.chat.completions.create(
            model="gpt-4o-mini",  # allows 128k tokens
            temperature=0.5,
            messages=[
                {
                    "role": "user",
                    "content": rendered_template,
                },
                #     {
                #         "role": "system",
                #         "content": """
                # Session Replay is PostHog's tool to record visits to web sites and apps.
                # We also gather events that occur like mouse clicks and key presses.
                # You write two or three sentence concise and simple summaries of those sessions based on a prompt.
                # You are more likely to mention errors or things that look like business success such as checkout events.
                # You always try to make the summary actionable. E.g. mentioning what someone clicked on, or summarizing errors they experienced.
                # You don't help with other knowledge.""",
                #     },
                #     {
                #         "role": "user",
                #         "content": f"""the session metadata I have is {session_metadata_dict}.
                # it gives an overview of activity and duration""",
                #     },
                #     {
                #         "role": "user",
                #         "content": f"""
                # URLs associated with the events can be found in this mapping {prompt_data.url_mapping}. You never refer to URLs by their placeholder. Always refer to the URL with the simplest version e.g. posthog.com or posthog.com/replay
                # """,
                #     },
                #     {
                #         "role": "user",
                #         "content": f"""the session events I have are {prompt_data.results}.
                # with columns {prompt_data.columns}.
                # they give an idea of what happened and when,
                # if present the elements_chain_texts, elements_chain_elements, and elements_chain_href extracted from the html can aid in understanding what a user interacted with
                # but should not be directly used in your response""",
                #     },
                #     {
                #         "role": "user",
                #         "content": """
                # generate a two or three sentence summary of the session.
                # only summarize, don't offer advice.
                # use as concise and simple language as is possible.
                # Dont' refer to the session length unless it is notable for some reason.
                # assume a reading age of around 12 years old.
                # generate no text other than the summary.""",
                #     },
            ],
            user=f"{instance_region}/{user.pk}",  # allows 8k tokens
        )

        usage = result.usage.prompt_tokens if result.usage else None
        if usage:
            TOKENS_IN_PROMPT_HISTOGRAM.observe(usage)

    content: str = result.choices[0].message.content or ""
    return {"content": content, "timings": timer.get_all_timings()}
