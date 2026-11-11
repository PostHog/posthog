import os
from collections.abc import Mapping
from functools import cache
from typing import Any, Optional

from django.conf import settings

import openai
import posthoganalytics
from openai.types.chat import ChatCompletion
from posthoganalytics.ai.openai import OpenAI

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_openai_client, resolve_ai_gateway_config


@cache
def _get_openai_client() -> Optional[OpenAI]:
    if not os.getenv("OPENAI_API_KEY"):
        return None
    return OpenAI(posthog_client=posthoganalytics.setup(), base_url=settings.OPENAI_BASE_URL)


@frozen
class OpenAICompletion:
    content: str
    prompt_tokens: int
    completion_tokens: int


def hit_openai(
    messages: list[openai.types.chat.ChatCompletionMessageParam],
    user: str,
    posthog_properties: Optional[dict[str, Any]] = None,
    posthog_groups: Optional[dict[str, Any]] = None,
    timeout: float | None = None,
    response_format: dict[str, Any] | None = None,
    distinct_id: str | None = None,
) -> OpenAICompletion:
    # Only forward optional params when set, so callers that don't need them keep the client defaults.
    optional_params: dict[str, Any] = {}
    if timeout is not None:
        optional_params["timeout"] = timeout
    if response_format is not None:
        optional_params["response_format"] = response_format

    if resolve_ai_gateway_config() is not None:
        properties = posthog_properties or {}
        gateway_client = build_openai_client(
            "django",
            ai_product=properties.get("ai_product"),
            properties=_gateway_labels(properties),
            distinct_id=distinct_id,
        )
        with gateway_client:
            result = gateway_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                temperature=0,
                messages=messages,
                user=user,
                **optional_params,
            )
        return _to_completion(result)

    openai_client = _get_openai_client()
    if not openai_client:
        raise ValueError("OPENAI_API_KEY environment variable not set")

    result = openai_client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        temperature=0,
        messages=messages,
        user=user,  # The user ID is for tracking within OpenAI in case of overuse/abuse
        posthog_distinct_id=distinct_id,
        posthog_properties=posthog_properties,
        posthog_groups=posthog_groups,
        **optional_params,
    )
    return _to_completion(result)


def _gateway_labels(properties: Mapping[str, Any]) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in properties.items()
        if value is not None and key != "ai_product" and not key.startswith("$")
    }


def _to_completion(result: ChatCompletion) -> OpenAICompletion:
    content: str = ""
    if result.choices[0] and result.choices[0].message.content:
        content = result.choices[0].message.content.removesuffix(";")
    prompt_tokens, completion_tokens = 0, 0
    if result.usage:
        prompt_tokens, completion_tokens = result.usage.prompt_tokens, result.usage.completion_tokens
    return OpenAICompletion(content=content, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
