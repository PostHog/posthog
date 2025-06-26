from openai import AsyncOpenAI, AsyncStream
import structlog
from ee.hogai.session_summaries.constants import SESSION_SUMMARIES_MODEL, SESSION_SUMMARIES_TEMPERATURE
from posthog.utils import get_instance_region
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

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
        messages.append({"role": "assistant", "content": assistant_start_text})
    if not messages:
        raise ValueError(f"No messages to send to LLM for session_id {session_id}")
    return messages


def _prepare_user_param(user_key: int) -> str:
    instance_region = get_instance_region() or "HOBBY"
    user_param = f"{instance_region}/{user_key}"
    return user_param


async def stream_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
    model: str = SESSION_SUMMARIES_MODEL,
) -> AsyncStream[ChatCompletionChunk]:
    """
    LLM streaming call.
    """
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)
    # TODO: Add LLM observability tracking here
    client = AsyncOpenAI()
    stream = await client.chat.completions.create(
        model=model,
        temperature=SESSION_SUMMARIES_TEMPERATURE,
        messages=messages,
        user=user_param,
        stream=True,
    )
    return stream


async def call_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
    model: str = SESSION_SUMMARIES_MODEL,
) -> ChatCompletion:
    """
    LLM non-streaming call.
    """
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)
    # TODO: Add LLM observability tracking here
    client = AsyncOpenAI()
    result = await client.chat.completions.create(
        model=model,
        temperature=SESSION_SUMMARIES_TEMPERATURE,
        messages=messages,
        user=user_param,
    )
    return result
