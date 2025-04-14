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
    rendered_summary_template: str, user: User, allowed_event_ids: list[str], session_id: str
):
    # TODO: Pre-filling LLM response usually improves the format of the response, test if it's needed here
    # assistant_start_text = "```yaml\nsummary: "
    # Get the LLM response
    try:
        llm_response = call_llm(input_prompt=rendered_summary_template, user_key=user.pk)
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


def call_llm(input_prompt: str, user_key: int, assistant_start_text: str | None = None) -> ChatCompletion:
    instance_region = get_instance_region() or "HOBBY"
    messages = [
        {
            "role": "user",
            "content": input_prompt,
        },
        # TODO Integrate good parts from the parts below into the new prompt
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
    ]
    if assistant_start_text:
        # Force LLM to start with the assistant text
        # TODO Check why the pre-defining the response with assistant text doesn't work properly
        # (for example, LLM still starts with ```yaml, while it should continue the assistant text)
        messages.append({"role": "assistant", "content": assistant_start_text})
    # TODO Make temperature/top_p/max_tokens configurable through input to use for different prompts
    result = openai.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.5,
        messages=messages,  # type: ignore
        user=f"{instance_region}/{user_key}",
    )
    return result
