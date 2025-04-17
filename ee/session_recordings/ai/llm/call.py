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


def call_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
    model: str = "o4-mini-2025-04-16",
) -> ChatCompletion:
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)
    # TODO Make model/reasoning_effort/temperature/top_p/max_tokens configurable through input to use for different prompts
    result = openai.chat.completions.create(
        model=model,
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
    model: str = "o4-mini-2025-04-16",
) -> Generator[ChatCompletionChunk, None, None]:
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)
    # TODO Make model/reasoning_effort/temperature/top_p/max_tokens configurable through input to use for different promp
    stream = openai.chat.completions.create(
        model=model,
        # TODO: Start with low reasoning for faster responses, iterate afterward based on user experience
        reasoning_effort="low",
        messages=messages,  # type: ignore
        user=user_param,
        stream=True,
    )
    yield from stream
