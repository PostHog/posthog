from datetime import datetime
import json
from typing import Any
from jsonschema import ValidationError
import openai
import structlog
from ee.session_recordings.ai.llm.call import stream_llm
from ee.session_recordings.ai.output_data import (
    enrich_raw_session_summary_with_events_meta,
    load_raw_session_summary_from_llm_content,
)
from ee.session_recordings.session_summary import ExceptionToRetry
from prometheus_client import Histogram
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_fixed, wait_random
from posthog.models.user import User
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from collections.abc import Generator

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


def _get_raw_content(llm_response: ChatCompletion | ChatCompletionChunk) -> str:
    if isinstance(llm_response, ChatCompletion):
        return llm_response.choices[0].message.content
    elif isinstance(llm_response, ChatCompletionChunk):
        return llm_response.choices[0].delta.content
    else:
        raise ValueError(f"Unexpected LLM response type: {type(llm_response)}")


def _serialize_to_sse_event(event_label: str, event_data: str) -> str:
    return f"event: {event_label}\ndata: {event_data}\n\n"


def _convert_llm_content_to_session_summary_stream_event(
    content: str,
    allowed_event_ids: list[str],
    session_id: str,
    simplified_events_mapping: dict[str, list[Any]],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
    session_start_time: datetime,
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
    session_summary = enrich_raw_session_summary_with_events_meta(
        raw_session_summary=raw_session_summary,
        simplified_events_mapping=simplified_events_mapping,
        simplified_events_columns=simplified_events_columns,
        url_mapping_reversed=url_mapping_reversed,
        window_mapping_reversed=window_mapping_reversed,
        session_start_time=session_start_time,
        session_id=session_id,
    )
    # If parsing succeeds, yield the new chunk
    sse_event_to_send = _serialize_to_sse_event(
        event_label="session-summary-stream", event_data=json.dumps(session_summary.data)
    )
    return sse_event_to_send


@retry(
    retry=retry_if_exception_type(ExceptionToRetry),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2) + wait_random(0, 10),
    retry_error_callback=_failed_stream_llm_summary,
)
def stream_llm_session_summary(
    summary_prompt: str,
    user: User,
    allowed_event_ids: list[str],
    session_id: str,
    simplified_events_mapping: dict[str, list[Any]],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
    session_start_time: datetime,
    system_prompt: str | None = None,
) -> Generator[str, None, None]:
    try:
        accumulated_content = ""
        accumulated_usage = 0
        # TODO: Find a way to time the first chunk and the time of total stream consumption (extend "openai_completion" timer)
        for chunk in stream_llm(
            input_prompt=summary_prompt, user_key=user.pk, session_id=session_id, system_prompt=system_prompt
        ):
            # TODO: Check if the usage is accumulated by itself or do we need to do it manually
            accumulated_usage += chunk.usage.prompt_tokens if chunk.usage else 0
            raw_content = _get_raw_content(chunk)
            if not raw_content:
                # If no content provided yet (for example, first streaming response), skip the chunk
                continue
            accumulated_content += raw_content
            try:
                intermediate_summary = _convert_llm_content_to_session_summary_stream_event(
                    content=accumulated_content,
                    allowed_event_ids=allowed_event_ids,
                    session_id=session_id,
                    simplified_events_mapping=simplified_events_mapping,
                    simplified_events_columns=simplified_events_columns,
                    url_mapping_reversed=url_mapping_reversed,
                    window_mapping_reversed=window_mapping_reversed,
                    session_start_time=session_start_time,
                )
                if not intermediate_summary:
                    continue
                yield intermediate_summary
            except ValidationError:
                # We can except incorrect schemas because of incomplete chunks, ok to skip some.
                # The stream should be retried only at the very end, when we have all the data.
                continue
            except ValueError as err:
                # The only way to raise ValueError is data hallucinations and inconsistencies (like missing mapping data).
                # Such exceptions should be retried as early as possible to decrease the latency of the stream.
                logger.exception(
                    f"Hallucinated data or inconsistencies in the session summary for session_id {session_id}: {err}"
                )
                raise ExceptionToRetry()
    except (openai.APIError, openai.APITimeoutError, openai.RateLimitError) as err:
        logger.exception(f"Error streaming LLM for session_id {session_id} by user {user.pk}: {err}")
        raise ExceptionToRetry()
    # Final validation of accumulated content (to decide if to retry the whole streamor not)
    try:
        if accumulated_usage:
            TOKENS_IN_PROMPT_HISTOGRAM.observe(accumulated_usage)
        final_summary = _convert_llm_content_to_session_summary_stream_event(
            content=accumulated_content,
            allowed_event_ids=allowed_event_ids,
            session_id=session_id,
            simplified_events_mapping=simplified_events_mapping,
            simplified_events_columns=simplified_events_columns,
            url_mapping_reversed=url_mapping_reversed,
            window_mapping_reversed=window_mapping_reversed,
            session_start_time=session_start_time,
        )
        if not final_summary:
            logger.exception(f"Final LLM content validation failed for session_id {session_id}")
            raise ValueError("Final content validation failed")
        # Yield the final validated summary
        yield final_summary
    # At this stage, when all the chunks are processed, any exception should be retried to ensure valid final content
    except (ValidationError, ValueError) as err:
        logger.exception(f"Failed to validate final LLM content for session_id {session_id}: {str(err)}")
        raise ExceptionToRetry()
