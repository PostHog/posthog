from django.conf import settings
from openai import AsyncStream
import structlog
from ee.hogai.session_summaries.constants import (
    SESSION_SUMMARIES_STREAMING_MODEL,
    SESSION_SUMMARIES_REASONING_EFFORT,
    SESSION_SUMMARIES_TEMPERATURE,
)
from posthoganalytics.ai.openai import OpenAI, AsyncOpenAI
from posthog.cloud_utils import is_cloud
from posthog.utils import get_instance_region
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
import os
from posthoganalytics.client import Client

import posthoganalytics
from rest_framework import exceptions

logger = structlog.get_logger(__name__)


def _get_default_posthog_client() -> Client:
    """Return the default analytics client after validating the environment."""
    if not settings.DEBUG and not is_cloud():
        raise exceptions.ValidationError("AI features are only available in PostHog Cloud")

    if not os.environ.get("OPENAI_API_KEY"):
        raise exceptions.ValidationError("OpenAI API key is not configured")

    client = posthoganalytics.default_client
    if not client:
        raise exceptions.ValidationError("PostHog analytics client is not configured")

    return client


def get_openai_client() -> OpenAI:
    """Get configured OpenAI client or raise appropriate error."""
    client = _get_default_posthog_client()
    return OpenAI(posthog_client=client)


def get_async_openai_client() -> AsyncOpenAI:
    """Get configured OpenAI client or raise appropriate error."""
    client = _get_default_posthog_client()
    return AsyncOpenAI(posthog_client=client)


def _prepare_messages(
    input_prompt: str, session_id: str, assistant_start_text: str | None = None, system_prompt: str | None = None
):
    """Compose message list for the OpenAI chat API."""
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
        raise ValueError(f"No messages to send to LLM for sessions: {session_id}")
    return messages


def _prepare_user_param(user_key: int) -> str:
    """Format user identifier for LLM calls."""
    instance_region = get_instance_region() or "HOBBY"
    user_param = f"{instance_region}/{user_key}"
    return user_param


async def stream_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
    model: str = SESSION_SUMMARIES_STREAMING_MODEL,
    trace_id: str | None = None,
) -> AsyncStream[ChatCompletionChunk]:
    """
    LLM streaming call.
    """
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)
    client = get_async_openai_client()
    stream: AsyncStream = await client.chat.completions.create(  # type: ignore[call-overload]
        messages=messages,
        model=model,
        temperature=SESSION_SUMMARIES_TEMPERATURE,
        user=user_param,
        stream=True,
        posthog_trace_id=trace_id,
    )
    return stream


async def call_llm(
    input_prompt: str,
    user_key: int,
    session_id: str,
    model: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
    reasoning: bool = False,
    trace_id: str | None = None,
) -> ChatCompletion:
    """
    LLM non-streaming call.
    """
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_key)
    client = get_async_openai_client()
    if not reasoning:
        result = await client.chat.completions.create(  # type: ignore[call-overload]
            messages=messages,
            model=model,
            temperature=SESSION_SUMMARIES_TEMPERATURE,
            user=user_param,
            posthog_trace_id=trace_id,
        )
    else:
        result = await client.chat.completions.create(  # type: ignore[call-overload]
            messages=messages,
            model=model,
            reasoning_effort=SESSION_SUMMARIES_REASONING_EFFORT,
            user=user_param,
            posthog_trace_id=trace_id,
        )
    return result
