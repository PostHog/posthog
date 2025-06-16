from dataclasses import dataclass
import datetime
import json
from pathlib import Path

import structlog
from ee.session_recordings.session_summary.input_data import (
    add_context_and_filter_events,
    get_session_events,
    get_session_metadata,
    get_team,
)
from ee.session_recordings.session_summary.prompt_data import SessionSummaryPromptData
from ee.session_recordings.session_summary.utils import load_custom_template, serialize_to_sse_event, shorten_url
from posthog.api.activity_log import ServerTimingsGathered
from posthog.session_recordings.models.metadata import RecordingMetadata
from posthog.warehouse.util import database_sync_to_async

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ExtraSummaryContext:
    focus_area: str | None = None


@dataclass(frozen=True)
class _SessionSummaryDBData:
    session_metadata: RecordingMetadata
    session_events_columns: list[str] | None
    session_events: list[tuple[str | datetime.datetime | list[str] | None, ...]] | None


@dataclass(frozen=True)
class _SessionSummaryPromptData:
    prompt_data: SessionSummaryPromptData
    simplified_events_mapping: dict[str, list[str | int | list[str] | None]]
    url_mapping_reversed: dict[str, str]
    window_mapping_reversed: dict[str, str]


@dataclass(frozen=True)
class _SessionSummaryPrompt:
    summary_prompt: str
    system_prompt: str


@dataclass(frozen=True)
class SingleSessionSummaryData:
    session_id: str
    user_pk: int
    prompt_data: _SessionSummaryPromptData | None
    prompt: _SessionSummaryPrompt | None
    sse_error_msg: str | None = None


@dataclass(frozen=True, kw_only=True)
class SingleSessionSummaryLlmInputs:
    """Data required to LLM-generate a summary for a single session"""

    session_id: str
    user_pk: int
    summary_prompt: str
    system_prompt: str
    simplified_events_mapping: dict[str, list[str | int | None | list[str]]]
    simplified_events_columns: list[str]
    url_mapping_reversed: dict[str, str]
    window_mapping_reversed: dict[str, str]
    session_start_time_str: str
    session_duration: int


async def get_session_data_from_db(
    session_id: str, team_id: int, timer: ServerTimingsGathered, local_reads_prod: bool
) -> _SessionSummaryDBData:
    with timer("get_team"):
        team = await database_sync_to_async(get_team)(team_id)
    with timer("get_metadata"):
        session_metadata = await database_sync_to_async(get_session_metadata)(
            session_id=session_id,
            team=team,
            local_reads_prod=local_reads_prod,
        )
    try:
        with timer("get_events"):
            session_events_columns, session_events = await database_sync_to_async(get_session_events)(
                team=team,
                session_metadata=session_metadata,
                session_id=session_id,
                local_reads_prod=local_reads_prod,
            )
    except ValueError as e:
        raw_error_message = str(e)
        if "No events found for session_id" in raw_error_message:
            # Stop processing early (as no events found) and return meaningful error message down the line
            return _SessionSummaryDBData(
                session_metadata=session_metadata,
                session_events_columns=None,
                session_events=None,
            )
        # Raise any unexpected errors
        raise
    with timer("add_context_and_filter"):
        session_events_columns, session_events = add_context_and_filter_events(session_events_columns, session_events)

    # TODO Get web analytics data on URLs to better understand what the user was doing
    # related to average visitors of the same pages (left the page too fast, unexpected bounce, etc.).
    # Keep in mind that in-app behavior (like querying insights a lot) differs from the web (visiting a lot of pages).

    # TODO Get product analytics data on custom events/funnels/conversions
    # to understand what actions are seen as valuable or are the part of the conversion flow

    # TODO Get feature flag data to understand what version of the app the user was using
    # and how different features enabled/disabled affect the session

    return _SessionSummaryDBData(
        session_metadata=session_metadata,
        session_events_columns=session_events_columns,
        session_events=session_events,
    )


def prepare_prompt_data(
    session_id: str,
    session_metadata: dict[str, str],
    session_events_columns: list[str],
    session_events: list[tuple[str | datetime.datetime | list[str] | None, ...]],
    timer: ServerTimingsGathered,
) -> _SessionSummaryPromptData:
    with timer("prepare_prompt_data"):
        prompt_data = SessionSummaryPromptData()
        simplified_events_mapping = prompt_data.load_session_data(
            raw_session_events=session_events,
            raw_session_metadata=session_metadata,
            raw_session_columns=session_events_columns,
            session_id=session_id,
        )
        if not prompt_data.metadata.start_time:
            raise ValueError(f"No start time found for session_id {session_id} when generating the prompt")
        # Reverse mappings for easier reference in the prompt.
        url_mapping_reversed = {v: k for k, v in prompt_data.url_mapping.items()}
        window_mapping_reversed = {v: k for k, v in prompt_data.window_id_mapping.items()}
    return _SessionSummaryPromptData(
        prompt_data=prompt_data,
        simplified_events_mapping=simplified_events_mapping,
        url_mapping_reversed=url_mapping_reversed,
        window_mapping_reversed=window_mapping_reversed,
    )


def generate_prompt(
    prompt_data: SessionSummaryPromptData,
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
    extra_summary_context: ExtraSummaryContext | None,
) -> _SessionSummaryPrompt:
    # Keep shortened URLs for the prompt to reduce the number of tokens
    short_url_mapping_reversed = {k: shorten_url(v) for k, v in url_mapping_reversed.items()}
    # Render all templates
    template_dir = Path(__file__).parent / "templates" / "identify-objectives"
    system_prompt = load_custom_template(
        template_dir,
        f"system-prompt.djt",
        {
            "FOCUS_AREA": extra_summary_context.focus_area if extra_summary_context else None,
        },
    )
    summary_example = load_custom_template(template_dir, f"example.yml")
    summary_prompt = load_custom_template(
        template_dir,
        f"prompt.djt",
        {
            "EVENTS_DATA": json.dumps(prompt_data.results),
            "SESSION_METADATA": json.dumps(prompt_data.metadata.to_dict()),
            "URL_MAPPING": json.dumps(short_url_mapping_reversed),
            "WINDOW_ID_MAPPING": json.dumps(window_mapping_reversed),
            "SUMMARY_EXAMPLE": summary_example,
            "FOCUS_AREA": extra_summary_context.focus_area if extra_summary_context else None,
        },
    )
    return _SessionSummaryPrompt(
        summary_prompt=summary_prompt,
        system_prompt=system_prompt,
    )


async def prepare_data_for_single_session_summary(
    session_id: str,
    user_pk: int,
    team_id: int,
    extra_summary_context: ExtraSummaryContext | None,
    local_reads_prod: bool = False,
) -> SingleSessionSummaryData:
    timer = ServerTimingsGathered()
    db_data = await get_session_data_from_db(
        session_id=session_id,
        team_id=team_id,
        timer=timer,
        local_reads_prod=local_reads_prod,
    )
    if not db_data.session_events or not db_data.session_events_columns:
        # Real-time replays could have no events yet, so we need to handle that case and show users a meaningful message
        sse_error_msg = serialize_to_sse_event(
            event_label="session-summary-error",
            event_data="No events found for this replay yet. Please try again in a few minutes.",
        )
        return SingleSessionSummaryData(
            session_id=session_id, user_pk=user_pk, prompt_data=None, prompt=None, sse_error_msg=sse_error_msg
        )
    prompt_data = prepare_prompt_data(
        session_id=session_id,
        # Convert to a dict, so that we can amend its values freely
        session_metadata=dict(db_data.session_metadata),  # type: ignore[arg-type]
        session_events_columns=db_data.session_events_columns,
        session_events=db_data.session_events,
        timer=timer,
    )
    prompt = generate_prompt(
        prompt_data=prompt_data.prompt_data,
        url_mapping_reversed=prompt_data.url_mapping_reversed,
        window_mapping_reversed=prompt_data.window_mapping_reversed,
        extra_summary_context=extra_summary_context,
    )
    return SingleSessionSummaryData(session_id=session_id, user_pk=user_pk, prompt_data=prompt_data, prompt=prompt)

    # TODO: Track the timing for streaming (inside the function, start before the request, end after the last chunk is consumed)
    # with timer("openai_completion"):
    # return {"content": session_summary.data, "timings_header": timer.to_header_string()}


def prepare_single_session_summary_input(
    session_id: str,
    user_pk: int,
    summary_data: SingleSessionSummaryData,
) -> SingleSessionSummaryLlmInputs:
    # Checking here instead of in the preparation function to keep mypy happy
    if summary_data.prompt_data is None:
        raise ValueError(f"Prompt data is missing for session_id {session_id}")
    if summary_data.prompt_data.prompt_data.metadata.start_time is None:
        raise ValueError(f"Session start time is missing in the session metadata for session_id {session_id}")
    if summary_data.prompt_data.prompt_data.metadata.duration is None:
        raise ValueError(f"Session duration is missing in the session metadata for session_id {session_id}")
    if summary_data.prompt is None:
        raise ValueError(f"Prompt is missing for session_id {session_id}")
    # Prepare the input
    input_data = SingleSessionSummaryLlmInputs(
        session_id=session_id,
        user_pk=user_pk,
        summary_prompt=summary_data.prompt.summary_prompt,
        system_prompt=summary_data.prompt.system_prompt,
        simplified_events_mapping=summary_data.prompt_data.simplified_events_mapping,
        simplified_events_columns=summary_data.prompt_data.prompt_data.columns,
        url_mapping_reversed=summary_data.prompt_data.url_mapping_reversed,
        window_mapping_reversed=summary_data.prompt_data.window_mapping_reversed,
        session_start_time_str=summary_data.prompt_data.prompt_data.metadata.start_time.isoformat(),
        session_duration=summary_data.prompt_data.prompt_data.metadata.duration,
    )
    return input_data
