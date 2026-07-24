import os

from django.conf import settings

import structlog
import posthoganalytics
from openai.types.responses import Response as OpenAIResponse
from posthoganalytics.ai.openai import AsyncOpenAI, OpenAI
from posthoganalytics.client import Client
from rest_framework import exceptions

from posthog.cloud_utils import is_cloud
from posthog.utils import get_instance_region

from ee.hogai.session_summaries.constants import BASE_LLM_CALL_TIMEOUT_S, SESSION_SUMMARIES_REASONING_EFFORT

logger = structlog.get_logger(__name__)

# Model name prefixes this module's OpenAI-compatible client cannot serve. The session-summary
# video pipeline talks to Gemini through the Google genai client (see the video-based activities);
# `call_llm` only reaches the OpenAI Responses API. A Gemini/Anthropic model arriving here is always
# a misroute — e.g. the video model passed while `video_based` was left at its `False` default — so
# we fail fast and loud instead of shipping it to OpenAI for a silent `model_not_found` 400.
_NON_OPENAI_MODEL_PREFIXES: tuple[str, ...] = ("gemini", "claude", "anthropic")


def _assert_openai_servable_model(model: str, session_id: str) -> None:
    """Reject non-OpenAI models before they reach the OpenAI Responses API."""
    normalized = model.lower().removeprefix("models/")
    if normalized.startswith(_NON_OPENAI_MODEL_PREFIXES):
        msg = (
            f"Non-OpenAI model '{model}' was routed to the OpenAI Responses API for session {session_id}. "
            "This text path only serves OpenAI models; Gemini models must go through the video pipeline "
            "(genai client). Ensure the caller sets video_based=True or passes an OpenAI-served model."
        )
        logger.error(msg, session_id=session_id, model=model, signals_type="session-summaries")
        raise ValueError(msg)


def _build_posthog_props(trigger_session_id: str | None) -> dict[str, str]:
    props: dict[str, str] = {"ai_product": "session_replay"}
    if trigger_session_id:
        props["$session_id"] = trigger_session_id
    return props


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
    return OpenAI(posthog_client=client, timeout=BASE_LLM_CALL_TIMEOUT_S, base_url=settings.OPENAI_BASE_URL)


def get_async_openai_client() -> AsyncOpenAI:
    """Get configured OpenAI client or raise appropriate error."""
    client = _get_default_posthog_client()
    return AsyncOpenAI(posthog_client=client, timeout=BASE_LLM_CALL_TIMEOUT_S, base_url=settings.OPENAI_BASE_URL)


def _prepare_messages(
    input_prompt: str, session_id: str, assistant_start_text: str | None = None, system_prompt: str | None = None
) -> list[dict[str, str]]:
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
        msg = f"No messages to send to LLM for sessions: {session_id}"
        logger.error(msg, session_id=session_id, signals_type="session-summaries")
        raise ValueError(msg)
    return messages


def _prepare_user_param(user_key: int) -> str:
    """Format user identifier for LLM calls."""
    instance_region = get_instance_region() or "HOBBY"
    user_param = f"{instance_region}/{user_key}"
    return user_param


async def call_llm(
    input_prompt: str,
    *,
    session_id: str,
    model: str,
    assistant_start_text: str | None = None,
    system_prompt: str | None = None,
    trace_id: str | None = None,
    user_id: int,
    user_distinct_id: str | None = None,
    trigger_session_id: str | None = None,
) -> OpenAIResponse:
    """
    LLM call using the Responses API.
    """
    _assert_openai_servable_model(model, session_id)
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_id)
    client = get_async_openai_client()
    posthog_props = _build_posthog_props(trigger_session_id)
    result = await client.responses.create(  # type: ignore[call-overload]
        input=messages,
        model=model,
        reasoning={"effort": SESSION_SUMMARIES_REASONING_EFFORT},
        user=user_param,
        posthog_trace_id=trace_id,
        posthog_distinct_id=user_distinct_id,
        posthog_properties=posthog_props,
    )
    return result
