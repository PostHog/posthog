from datetime import datetime
import json
import os
from typing import Any
import openai
import structlog
from ee.session_recordings.session_summary.llm.call import stream_llm
from ee.session_recordings.session_summary.output_data import (
    enrich_raw_session_summary_with_meta,
    load_raw_session_summary_from_llm_content,
)
from ee.session_recordings.session_summary import ExceptionToRetry, SummaryValidationError
from prometheus_client import Histogram
from tenacity import RetryCallState
from ee.session_recordings.session_summary.utils import serialize_to_sse_event
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from collections.abc import AsyncGenerator

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


def _failed_stream_llm_summary(
    retry_state: RetryCallState,
) -> None:
    logger.exception(
        f"Couldn't generate session summary through LLM with {retry_state.attempt_number} attempts "
        f"({round(retry_state.idle_for, 2)}s). Raising an exception."
    )
    raise Exception("Couldn't generate session summary through LLM")


def _get_raw_content(llm_response: ChatCompletion | ChatCompletionChunk, session_id: str) -> str:
    if isinstance(llm_response, ChatCompletion):
        content = llm_response.choices[0].message.content
    elif isinstance(llm_response, ChatCompletionChunk):
        content = llm_response.choices[0].delta.content
    else:
        raise ValueError(f"Unexpected LLM response type for session_id {session_id}: {type(llm_response)}")
    return content if content else ""


def _convert_llm_content_to_session_summary_json(
    content: str,
    allowed_event_ids: list[str],
    session_id: str,
    simplified_events_mapping: dict[str, list[Any]],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
    summary_prompt: str,
    session_start_time_str: str,
    session_duration: int,
    final_validation: bool = False,
) -> str | None:
    # Try to parse the accumulated text as YAML
    raw_session_summary = load_raw_session_summary_from_llm_content(
        raw_content=content, allowed_event_ids=allowed_event_ids, session_id=session_id
    )
    if not raw_session_summary:
        # If parsing fails, this chunk is incomplete, so skipping it.
        # We'll accumulate more chunks until we get valid YAML again.
        return None
    # Enrich session summary with events metadata
    session_summary = enrich_raw_session_summary_with_meta(
        raw_session_summary=raw_session_summary,
        simplified_events_mapping=simplified_events_mapping,
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


async def stream_llm_session_summary(
    summary_prompt: str,
    user_pk: int,
    allowed_event_ids: list[str],
    session_id: str,
    simplified_events_mapping: dict[str, list[Any]],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
    session_start_time_str: str,
    session_duration: int,
    system_prompt: str | None = None,
) -> AsyncGenerator[str, None]:
    try:
        accumulated_content = ""
        accumulated_usage = 0
        # TODO: Find a way to time the first chunk and the time of total stream consumption (extend "openai_completion" timer)
        stream = await stream_llm(
            input_prompt=summary_prompt, user_key=user_pk, session_id=session_id, system_prompt=system_prompt
        )
        async for chunk in stream:
            # TODO: Check if the usage is accumulated by itself or do we need to do it manually
            accumulated_usage += chunk.usage.prompt_tokens if chunk.usage else 0
            raw_content = _get_raw_content(chunk, session_id)
            if not raw_content:
                # If no content provided yet (for example, first streaming response), skip the chunk
                continue
            accumulated_content += raw_content
            try:
                intermediate_summary = _convert_llm_content_to_session_summary_json(
                    content=accumulated_content,
                    allowed_event_ids=allowed_event_ids,
                    session_id=session_id,
                    simplified_events_mapping=simplified_events_mapping,
                    simplified_events_columns=simplified_events_columns,
                    url_mapping_reversed=url_mapping_reversed,
                    window_mapping_reversed=window_mapping_reversed,
                    session_start_time_str=session_start_time_str,
                    session_duration=session_duration,
                    summary_prompt=summary_prompt,
                )
                if not intermediate_summary:
                    continue
                # If parsing succeeds, yield the new chunk
                sse_event_to_send = serialize_to_sse_event(
                    event_label="session-summary-stream", event_data=intermediate_summary
                )
                yield sse_event_to_send
            except SummaryValidationError:
                # We can accept incorrect schemas because of incomplete chunks, ok to skip some.
                # The stream should be retried only at the very end, when we have all the data.
                continue
            except ValueError as err:
                # The only way to raise ValueError is data hallucinations and inconsistencies (like missing mapping data).
                # Such exceptions should be retried as early as possible to decrease the latency of the stream.
                logger.exception(
                    f"Hallucinated data or inconsistencies in the session summary for session_id {session_id}: {err}",
                    session_id=session_id,
                    user_pk=user_pk,
                )
                raise ExceptionToRetry()
    except (openai.APIError, openai.APITimeoutError, openai.RateLimitError) as err:
        # TODO: Use posthoganalytics.capture_exception where applicable, add replay_feature
        logger.exception(
            f"Error streaming LLM for session_id {session_id} by user {user_pk}: {err}",
            session_id=session_id,
            user_pk=user_pk,
        )
        raise ExceptionToRetry()
    # Final validation of accumulated content (to decide if to retry the whole stream or not)
    try:
        if accumulated_usage:
            TOKENS_IN_PROMPT_HISTOGRAM.observe(accumulated_usage)
        final_summary = _convert_llm_content_to_session_summary_json(
            content=accumulated_content,
            allowed_event_ids=allowed_event_ids,
            session_id=session_id,
            simplified_events_mapping=simplified_events_mapping,
            simplified_events_columns=simplified_events_columns,
            url_mapping_reversed=url_mapping_reversed,
            window_mapping_reversed=window_mapping_reversed,
            session_start_time_str=session_start_time_str,
            session_duration=session_duration,
            summary_prompt=summary_prompt,
            final_validation=True,
        )
        if not final_summary:
            logger.exception(
                f"Final LLM content validation failed for session_id {session_id}",
                session_id=session_id,
                user_pk=user_pk,
            )
            raise ValueError("Final content validation failed")

        # If parsing succeeds, yield the final validated summary
        sse_event_to_send = serialize_to_sse_event(event_label="session-summary-stream", event_data=final_summary)
        yield sse_event_to_send
    # At this stage, when all the chunks are processed, any exception should be retried to ensure valid final content
    except (SummaryValidationError, ValueError) as err:
        logger.exception(
            f"Failed to validate final LLM content for session_id {session_id}: {str(err)}",
            session_id=session_id,
            user_pk=user_pk,
        )
        raise ExceptionToRetry()


def _track_session_summary_generation(
    summary_prompt: str, raw_session_summary: str, session_summary: str, results_base_dir_path: str
) -> None:
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
