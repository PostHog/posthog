import openai
import structlog
from ee.session_recordings.ai.output_data import load_raw_session_summary_from_llm_content
from ee.session_recordings.session_summary import ExceptionToRetry
from prometheus_client import Histogram
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_fixed, wait_random
from posthog.models.user import User
from posthog.utils import get_instance_region
from openai.types.chat.chat_completion import ChatCompletion

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


@retry(
    retry=retry_if_exception_type(ExceptionToRetry),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2) + wait_random(0, 10),
    retry_error_callback=_failed_get_llm_summary,
)
def get_raw_llm_session_summary(
    summary_prompt: str, user: User, allowed_event_ids: list[str], session_id: str, system_prompt: str | None = None
):
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
        raw_session_summary = load_raw_session_summary_from_llm_content(
            llm_response=llm_response, allowed_event_ids=allowed_event_ids, session_id=session_id
        )
    # Validation errors should be retried if LLM wasn't able to generate a valid schema from the first attempt
    except ValueError as err:
        # TODO: Instead of running the whole call, could ask LLM to fix the error instead (faster)
        logger.exception(
            f"Error loading raw session summary from LLM for session_id {session_id} by user {user.pk}, retrying: {err}"
        )
        raise ExceptionToRetry()
    return raw_session_summary


def call_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
) -> ChatCompletion:
    instance_region = get_instance_region() or "HOBBY"
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
    # TODO Make temperature/top_p/max_tokens configurable through input to use for different prompts
    result = openai.chat.completions.create(
        model="o3-mini-2025-01-31",
        # TODO: Start with low reasoning for faster responses, iterate afterward based on user experience
        reasoning_effort="low",
        messages=messages,  # type: ignore
        user=f"{instance_region}/{user_key}",
    )
    return result
