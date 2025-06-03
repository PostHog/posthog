import openai
import structlog
from posthog.utils import get_instance_region
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from collections.abc import Generator

logger = structlog.get_logger(__name__)


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


def stream_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
    # TODO Make model/reasoning_effort/temperature/top_p/max_tokens configurable through input instead of hardcoding
    model: str = "gpt-4.1-2025-04-14",
) -> Generator[ChatCompletionChunk, None, None]:
    """
    LLM streaming call.
    """
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)

    # TODO: Spend more time on testing reasoning vs regular modelds, start with regular because of faster streaming
    # model: str = "o4-mini-2025-04-16",
    # reasoning_effort="medium",

    # TODO: Add LLM observability tracking her
    stream = openai.chat.completions.create(
        model=model,
        temperature=0.1,  # Using 0.1 to reduce hallucinations, but >0 to allow for some creativity
        messages=messages,
        user=user_param,
        stream=True,
    )
    yield from stream


def call_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
    model: str = "gpt-4.1-2025-04-14",
) -> ChatCompletion:
    """
    LLM sync call.
    """
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)
    result = openai.chat.completions.create(
        model=model,
        temperature=0.1,
        messages=messages,
        user=user_param,
    )
    return result
