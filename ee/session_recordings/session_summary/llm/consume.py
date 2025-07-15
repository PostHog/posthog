from datetime import datetime
import json
import os
from typing import Any
import openai
import structlog
from ee.hogai.session_summaries.constants import SESSION_SUMMARIES_SYNC_MODEL
from ee.session_recordings.session_summary.llm.call import call_llm, stream_llm
from ee.session_recordings.session_summary.output_data import (
    enrich_raw_session_summary_with_meta,
    load_raw_session_summary_from_llm_content,
)
from ee.session_recordings.session_summary import ExceptionToRetry, SummaryValidationError
from prometheus_client import Histogram
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from collections.abc import AsyncGenerator

from ee.session_recordings.session_summary.patterns.output_data import (
    RawSessionGroupPatternAssignmentsList,
    RawSessionGroupSummaryPatternsList,
    load_pattern_assignments_from_llm_content,
    load_patterns_from_llm_content,
)
from ee.session_recordings.session_summary.summarize_session import PatternsPrompt

logger = structlog.get_logger(__name__)

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


def _get_raw_content(llm_response: ChatCompletion | ChatCompletionChunk) -> str:
    """Return text content from a ChatCompletion or streaming chunk."""
    if isinstance(llm_response, ChatCompletion):
        content = llm_response.choices[0].message.content
    elif isinstance(llm_response, ChatCompletionChunk):
        content = llm_response.choices[0].delta.content
    return content if content else ""


def _convert_llm_content_to_session_summary_json_str(
    content: str,
    allowed_event_ids: list[str],
    session_id: str,
    simplified_events_mapping: dict[str, list[Any]],
    event_ids_mapping: dict[str, str],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
    summary_prompt: str,
    session_start_time_str: str,
    session_duration: int,
    final_validation: bool = False,
) -> str | None:
    """Parse and enrich LLM YAML output, returning a JSON string."""
    # Try to parse the accumulated text as YAML
    raw_session_summary = load_raw_session_summary_from_llm_content(
        raw_content=content, allowed_event_ids=allowed_event_ids, session_id=session_id
    )
    if not raw_session_summary:
        # If parsing fails, this chunk is incomplete or call response is hallucinated, so skipping it.
        return None
    # Enrich session summary with events metadata
    session_summary = enrich_raw_session_summary_with_meta(
        raw_session_summary=raw_session_summary,
        simplified_events_mapping=simplified_events_mapping,
        event_ids_mapping=event_ids_mapping,
        simplified_events_columns=simplified_events_columns,
        url_mapping_reversed=url_mapping_reversed,
        window_mapping_reversed=window_mapping_reversed,
        session_start_time_str=session_start_time_str,
        session_duration=session_duration,
        session_id=session_id,
    )
    # Track generation for history of experiments
    if final_validation and os.environ.get("LOCAL_SESSION_SUMMARY_RESULTS_DIR"):
        _track_session_summary_generation(
            summary_prompt=summary_prompt,
            raw_session_summary=json.dumps(raw_session_summary.data, indent=4),
            session_summary=json.dumps(session_summary.data, indent=4),
            results_base_dir_path=os.environ["LOCAL_SESSION_SUMMARY_RESULTS_DIR"],
        )
    return json.dumps(session_summary.data)


async def get_llm_session_group_patterns_extraction(
    prompt: PatternsPrompt, user_id: int, session_ids: list[str], trace_id: str | None = None
) -> RawSessionGroupSummaryPatternsList:
    """Call LLM to extract patterns from multiple sessions."""
    sessions_identifier = ",".join(session_ids)
    result = await call_llm(
        input_prompt=prompt.patterns_prompt,
        user_key=user_id,
        session_id=sessions_identifier,
        system_prompt=prompt.system_prompt,
        model=SESSION_SUMMARIES_SYNC_MODEL,
        reasoning=True,
        trace_id=trace_id,
    )
    raw_content = _get_raw_content(result)
    if not raw_content:
        raise ValueError(
            f"No content consumed when calling LLM for session group patterns extraction, sessions {sessions_identifier}"
        )
    patterns = load_patterns_from_llm_content(raw_content, sessions_identifier)
    return patterns


async def get_llm_session_group_patterns_assignment(
    prompt: PatternsPrompt, user_id: int, session_ids: list[str], trace_id: str | None = None
) -> RawSessionGroupPatternAssignmentsList:
    """Call LLM to assign events to extracted patterns."""
    sessions_identifier = ",".join(session_ids)
    result = await call_llm(
        input_prompt=prompt.patterns_prompt,
        user_key=user_id,
        session_id=sessions_identifier,
        system_prompt=prompt.system_prompt,
        model=SESSION_SUMMARIES_SYNC_MODEL,
        reasoning=True,
        trace_id=trace_id,
    )
    raw_content = _get_raw_content(result)
    if not raw_content:
        raise ValueError(
            f"No content consumed when calling LLM for session group patterns assignment, sessions {sessions_identifier}"
        )
    patterns = load_pattern_assignments_from_llm_content(raw_content, sessions_identifier)
    return patterns


async def get_llm_single_session_summary(
    summary_prompt: str,
    user_id: int,
    allowed_event_ids: list[str],
    session_id: str,
    simplified_events_mapping: dict[str, list[Any]],
    event_ids_mapping: dict[str, str],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
    session_start_time_str: str,
    session_duration: int,
    system_prompt: str | None = None,
    trace_id: str | None = None,
) -> str:
    """Generate a single session summary in one LLM call."""
    try:
        result = await call_llm(
            input_prompt=summary_prompt,
            user_key=user_id,
            session_id=session_id,
            system_prompt=system_prompt,
            model=SESSION_SUMMARIES_SYNC_MODEL,
            reasoning=True,
            trace_id=trace_id,
        )
        raw_content = _get_raw_content(result)
        if not raw_content:
            raise ValueError(f"No content consumed when calling LLM for session summary, sessions {session_id}")
        session_summary_str = _convert_llm_content_to_session_summary_json_str(
            content=raw_content,
            allowed_event_ids=allowed_event_ids,
            session_id=session_id,
            simplified_events_mapping=simplified_events_mapping,
            event_ids_mapping=event_ids_mapping,
            simplified_events_columns=simplified_events_columns,
            url_mapping_reversed=url_mapping_reversed,
            window_mapping_reversed=window_mapping_reversed,
            session_start_time_str=session_start_time_str,
            session_duration=session_duration,
            summary_prompt=summary_prompt,
            final_validation=True,
        )
        if not session_summary_str:
            raise ValueError(
                f"Failed to parse LLM response for session summary, session_id {session_id}: {raw_content}"
            )
        # If parsing succeeds, yield the new chunk
        return session_summary_str
    except (SummaryValidationError, ValueError) as err:
        # The only way to raise such errors is data hallucinations and inconsistencies (like missing mapping data).
        # Such exceptions should be retried as early as possible to decrease the latency of the call.
        logger.exception(
            f"Hallucinated data or inconsistencies in the session summary for session_id {session_id} (get): {err}",
            session_id=session_id,
            user_id=user_id,
        )
        raise ExceptionToRetry() from err
    except (openai.APIError, openai.APITimeoutError, openai.RateLimitError) as err:
        # TODO: Use posthoganalytics.capture_exception where applicable, add replay_feature
        logger.exception(
            f"Error calling LLM for session_id {session_id} by user {user_id}: {err}",
            session_id=session_id,
            user_id=user_id,
        )
        raise ExceptionToRetry() from err


async def stream_llm_single_session_summary(
    summary_prompt: str,
    user_id: int,
    allowed_event_ids: list[str],
    session_id: str,
    simplified_events_mapping: dict[str, list[Any]],
    event_ids_mapping: dict[str, str],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
    session_start_time_str: str,
    session_duration: int,
    system_prompt: str | None = None,
    trace_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream LLM summary for a session, yielding JSON chunks."""
    try:
        accumulated_content = ""
        accumulated_usage = 0
        stream = await stream_llm(
            input_prompt=summary_prompt,
            user_key=user_id,
            session_id=session_id,
            system_prompt=system_prompt,
            trace_id=trace_id,
        )
        async for chunk in stream:
            accumulated_usage += chunk.usage.prompt_tokens if chunk.usage else 0
            raw_content = _get_raw_content(chunk)
            if not raw_content:
                # If no content provided yet (for example, first streaming response), skip the chunk
                continue
            accumulated_content += raw_content
            try:
                intermediate_summary_str = _convert_llm_content_to_session_summary_json_str(
                    content=accumulated_content,
                    allowed_event_ids=allowed_event_ids,
                    session_id=session_id,
                    simplified_events_mapping=simplified_events_mapping,
                    event_ids_mapping=event_ids_mapping,
                    simplified_events_columns=simplified_events_columns,
                    url_mapping_reversed=url_mapping_reversed,
                    window_mapping_reversed=window_mapping_reversed,
                    session_start_time_str=session_start_time_str,
                    session_duration=session_duration,
                    summary_prompt=summary_prompt,
                )
                if not intermediate_summary_str:
                    continue
                # If parsing succeeds, yield the new chunk
                yield intermediate_summary_str
            except SummaryValidationError:
                # We can accept incorrect schemas because of incomplete chunks, ok to skip some.
                # The stream should be retried only at the very end, when we have all the data.
                continue
            except ValueError as err:
                # The only way to raise ValueError is data hallucinations and inconsistencies (like missing mapping data).
                # Such exceptions should be retried as early as possible to decrease the latency of the stream.
                logger.exception(
                    f"Hallucinated data or inconsistencies in the session summary for session_id {session_id} (stream): {err}",
                    session_id=session_id,
                    user_id=user_id,
                )
                raise ExceptionToRetry() from err
    except (openai.APIError, openai.APITimeoutError, openai.RateLimitError) as err:
        # TODO: Use posthoganalytics.capture_exception where applicable, add replay_feature
        logger.exception(
            f"Error streaming LLM for session_id {session_id} by user {user_id}: {err}",
            session_id=session_id,
            user_id=user_id,
        )
        raise ExceptionToRetry() from err
    # Final validation of accumulated content (to decide if to retry the whole stream or not)
    try:
        if accumulated_usage:
            TOKENS_IN_PROMPT_HISTOGRAM.observe(accumulated_usage)
        final_summary_str = _convert_llm_content_to_session_summary_json_str(
            content=accumulated_content,
            allowed_event_ids=allowed_event_ids,
            session_id=session_id,
            simplified_events_mapping=simplified_events_mapping,
            event_ids_mapping=event_ids_mapping,
            simplified_events_columns=simplified_events_columns,
            url_mapping_reversed=url_mapping_reversed,
            window_mapping_reversed=window_mapping_reversed,
            session_start_time_str=session_start_time_str,
            session_duration=session_duration,
            summary_prompt=summary_prompt,
            final_validation=True,
        )
        if not final_summary_str:
            logger.exception(
                f"Final LLM content validation failed for session_id {session_id}",
                session_id=session_id,
                user_id=user_id,
            )
            raise ValueError("Final content validation failed")

        # If parsing succeeds, yield the final validated summary
        yield final_summary_str
    # At this stage, when all the chunks are processed, any exception should be retried to ensure valid final content
    except (SummaryValidationError, ValueError) as err:
        logger.exception(
            f"Failed to validate final LLM content for session_id {session_id}: {str(err)}",
            session_id=session_id,
            user_id=user_id,
        )
        raise ExceptionToRetry() from err


def _track_session_summary_generation(
    summary_prompt: str, raw_session_summary: str, session_summary: str, results_base_dir_path: str
) -> None:
    """Persist prompt/response pairs for offline analysis."""
    from pathlib import Path

    # Count how many child directories there are in the results_base_dir
    child_dirs = [d for d in Path(results_base_dir_path).iterdir() if d.is_dir()]
    datetime_marker = f"{len(child_dirs)}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    current_experiment_dir = Path(results_base_dir_path) / datetime_marker
    current_experiment_dir.mkdir(parents=True, exist_ok=True)
    # Store the prompt and response for results tracking
    with open(current_experiment_dir / f"prompt_{datetime_marker}.txt", "w") as f:
        f.write(summary_prompt)
    with open(current_experiment_dir / f"response_{datetime_marker}.yml", "w") as f:
        f.write(raw_session_summary)
    with open(current_experiment_dir / f"enriched_response_{datetime_marker}.yml", "w") as f:
        f.write(session_summary)
    template_dir = Path(__file__).parent.parent / "templates" / "identify-objectives"
    with open(template_dir / "prompt.djt") as fr:
        with open(current_experiment_dir / f"prompt_template_{datetime_marker}.txt", "w") as fw:
            fw.write(fr.read())
    with open(template_dir / "system-prompt.djt") as fr:
        with open(current_experiment_dir / f"system_prompt_{datetime_marker}.txt", "w") as fw:
            fw.write(fr.read())
    with open(template_dir / "example.yml") as fr:
        with open(current_experiment_dir / f"example_{datetime_marker}.yml", "w") as fw:
            fw.write(fr.read())
