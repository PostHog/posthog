import os
from typing import Any, Optional

from django.conf import settings

import openai
import posthoganalytics
from posthoganalytics.ai.openai import OpenAI

openai_client = (
    OpenAI(posthog_client=posthoganalytics, base_url=settings.OPENAI_BASE_URL) if os.getenv("OPENAI_API_KEY") else None  # type: ignore
)


def hit_openai(
    messages: list[openai.types.chat.ChatCompletionMessageParam],
    user: str,
    posthog_properties: Optional[dict[str, Any]] = None,
    posthog_groups: Optional[dict[str, Any]] = None,
    timeout: float | None = None,
    response_format: dict[str, Any] | None = None,
) -> tuple[str, int, int]:
    if not openai_client:
        raise ValueError("OPENAI_API_KEY environment variable not set")

    # Only forward optional params when set, so callers that don't need them keep the client defaults.
    optional_params: dict[str, Any] = {}
    if timeout is not None:
        optional_params["timeout"] = timeout
    if response_format is not None:
        optional_params["response_format"] = response_format

    result = openai_client.chat.completions.create(  # type: ignore
        model="gpt-4.1-mini",
        temperature=0,
        messages=messages,
        user=user,  # The user ID is for tracking within OpenAI in case of overuse/abuse
        posthog_properties=posthog_properties,
        posthog_groups=posthog_groups,
        **optional_params,
    )

    content: str = ""
    if result.choices[0] and result.choices[0].message.content:
        content = result.choices[0].message.content.removesuffix(";")
    prompt_tokens, completion_tokens = 0, 0
    if result.usage:
        prompt_tokens, completion_tokens = result.usage.prompt_tokens, result.usage.completion_tokens
    return content, prompt_tokens, completion_tokens
