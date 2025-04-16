import openai
import structlog
from ee.session_recordings.ai.output_data import RawSessionSummarySerializer, load_raw_session_summary_from_llm_content
from ee.session_recordings.session_summary import ExceptionToRetry
from prometheus_client import Histogram
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_fixed, wait_random
from posthog.models.user import User
from posthog.utils import get_instance_region
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from typing import Any
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


def _failed_get_llm_summary(
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


@retry(
    retry=retry_if_exception_type(ExceptionToRetry),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2) + wait_random(0, 10),
    retry_error_callback=_failed_get_llm_summary,
)
def get_raw_llm_session_summary(
    summary_prompt: str, user: User, allowed_event_ids: list[str], session_id: str, system_prompt: str | None = None
) -> RawSessionSummarySerializer:
    # TODO: Pre-filling LLM response usually improves the format of the response, test if it's needed here
    # assistant_start_text = "```yaml\nsummary: "
    # Get the LLM response
    try:
        llm_response = call_llm(
            input_prompt=summary_prompt, user_key=user.pk, session_id=session_id, system_prompt=system_prompt
        )
    # Retry on OpenAI errors that make sense to retry
    except (openai.APIError, openai.APITimeoutError, openai.RateLimitError) as err:
        logger.exception(f"Error calling LLM for session_id {session_id} by user {user.pk}, retrying: {err}")
        raise ExceptionToRetry()
    # Calculate/log the tokens usage
    usage = llm_response.usage.prompt_tokens if llm_response.usage else None
    if usage:
        TOKENS_IN_PROMPT_HISTOGRAM.observe(usage)
    # Ensure the LLM response is valid
    try:
        raw_content = _get_raw_content(llm_response)
        raw_session_summary = load_raw_session_summary_from_llm_content(
            raw_content=raw_content, allowed_event_ids=allowed_event_ids, session_id=session_id
        )
        if not raw_session_summary:
            raise ValueError(f"LLM returned empty session summary for session_id {session_id}")
    # Validation errors should be retried if LLM wasn't able to generate a valid schema from the first attempt
    except ValueError as err:
        # TODO: Instead of running the whole call, could ask LLM to fix the error instead (faster)
        logger.exception(
            f"Error loading raw session summary from LLM for session_id {session_id} by user {user.pk}, retrying: {err}"
        )
        raise ExceptionToRetry()
    return raw_session_summary


@retry(
    retry=retry_if_exception_type(ExceptionToRetry),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2) + wait_random(0, 10),
    retry_error_callback=_failed_get_llm_summary,
)
def stream_raw_llm_session_summary(
    summary_prompt: str, user: User, allowed_event_ids: list[str], session_id: str, system_prompt: str | None = None
) -> Generator[dict[str, Any], None, None]:
    try:
        accumulated_content = ""
        accumulated_usage = 0
        for chunk in stream_llm(
            input_prompt=summary_prompt, user_key=user.pk, session_id=session_id, system_prompt=system_prompt
        ):
            # TODO: Check if the usage is accumulated by itself or do we need to do it manually
            accumulated_usage += chunk.usage.prompt_tokens if chunk.usage else 0
            raw_content = _get_raw_content(chunk)
            if not raw_content:
                # If no content provided yet (for example, if streaming), skip the validation
                continue
            accumulated_content += raw_content
            try:
                # Try to parse the accumulated text as YAML
                raw_session_summary = load_raw_session_summary_from_llm_content(
                    raw_content=accumulated_content, allowed_event_ids=allowed_event_ids, session_id=session_id
                )
                if not raw_session_summary:
                    # If parsing fails, this chunk makes accumulated content invalid, so skipping it
                    # We'll accumulate more chunks until we get valid YAML again
                    continue
                # If parsing succeeds, yield the new chunk
                # TODO: Return back to summarizer when adding the enrichment
                yield raw_session_summary.data
            except ValueError:
                # The same logic, we can justify the retry for stream only
                # at the very end of stream when we are sure we have all the data
                continue
    except (openai.APIError, openai.APITimeoutError, openai.RateLimitError) as err:
        logger.exception(f"Error streaming LLM for session_id {session_id} by user {user.pk}: {err}")
        raise ExceptionToRetry()
    # Final validation of accumulated content (to decide if to retry or not)
    try:
        final_summary = load_raw_session_summary_from_llm_content(
            raw_content=accumulated_content, allowed_event_ids=allowed_event_ids, session_id=session_id
        )
        if not final_summary:
            logger.error(f"Final LLM content validation failed for session_id {session_id}")
            raise ValueError("Final content validation failed")
        if accumulated_usage:
            TOKENS_IN_PROMPT_HISTOGRAM.observe(accumulated_usage)
        # TODO: Return back to summarizer when adding the enrichment
        # Yield the final validated summary
        yield final_summary.data
    except ValueError as err:
        logger.exception(f"Failed to validate final LLM content for session_id {session_id}: {str(err)}")
        raise ExceptionToRetry()


def _prepare_messages(
    input_prompt: str, session_id: str, assistant_start_text: str | None = None, system_prompt: str | None = None
):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if input_prompt:
        messages.append(
            {
                "role": "user",
                "content": input_prompt,
            }
        )
    if assistant_start_text:
        # Force LLM to start with the assistant text
        # TODO Check why the pre-defining the response with assistant text doesn't work properly
        # (for example, LLM still starts with ```yaml, while it should continue the assistant text)
        messages.append({"role": "assistant", "content": assistant_start_text})
    if not messages:
        raise ValueError(f"No messages to send to LLM for session_id {session_id}")
    return messages


def _prepare_user_param(user_key: int) -> str:
    instance_region = get_instance_region() or "HOBBY"
    user_param = f"{instance_region}/{user_key}"
    return user_param


def call_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
) -> ChatCompletion:
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)
    # TODO Make temperature/top_p/max_tokens configurable through input to use for different prompts
    result = openai.chat.completions.create(
        model="o3-mini-2025-01-31",
        # TODO: Start with low reasoning for faster responses, iterate afterward based on user experience
        reasoning_effort="low",
        messages=messages,  # type: ignore
        user=user_param,
    )
    return result


def stream_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
) -> Generator[ChatCompletionChunk, None, None]:
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)
    stream = openai.chat.completions.create(
        model="o3-mini-2025-01-31",
        reasoning_effort="low",
        messages=messages,  # type: ignore
        user=user_param,
        stream=True,  # Enable streaming
    )
    yield from stream
