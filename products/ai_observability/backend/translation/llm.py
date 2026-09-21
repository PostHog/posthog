"""LLM-based translation using the LLM gateway."""

import structlog
from openai import APITimeoutError

from posthog.llm.gateway_client import get_llm_client

from .constants import SUPPORTED_LANGUAGES, TRANSLATION_MODEL, TRANSLATION_TIMEOUT_SECONDS

logger = structlog.get_logger(__name__)


class TranslationTimeoutError(Exception):
    """The model did not return a translation inside TRANSLATION_TIMEOUT_SECONDS."""


def translate_text(text: str, target_language: str, user_distinct_id: str | None = None) -> str:
    """
    Translate text to target language using the LLM gateway.

    Args:
        text: The text to translate
        target_language: Target language code (e.g., 'en', 'es', 'fr')
        user_distinct_id: The user's distinct_id for analytics attribution

    Returns:
        Translated text

    Raises:
        TranslationTimeoutError: The request exceeded TRANSLATION_TIMEOUT_SECONDS.
    """
    # A translation that runs out of time does so because the text is long and the model is slow,
    # not because the gateway blipped, so a second attempt spends the same budget to fail the same
    # way. The SDK retries twice by default, which makes the caller wait three timeouts before
    # seeing an error. One attempt with a larger budget fails sooner and leaves a text at the
    # 10,000 character cap more room to finish.
    client = get_llm_client("llma_translation").with_options(max_retries=0)

    target_name = SUPPORTED_LANGUAGES.get(target_language, target_language)

    try:
        response = client.chat.completions.create(
            model=TRANSLATION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": f"You are a translator. Translate the following text to {target_name}. "
                    "Only return the translation, nothing else. Preserve formatting and line breaks.",
                },
                {"role": "user", "content": text},
            ],
            timeout=TRANSLATION_TIMEOUT_SECONDS,
            user=user_distinct_id or "llma-translation",
        )
    except APITimeoutError as e:
        raise TranslationTimeoutError from e

    content = response.choices[0].message.content
    return content.strip() if content else ""
