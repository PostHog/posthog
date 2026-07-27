"""LLM-based translation using the LLM gateway."""

import structlog

from posthog.llm.gateway_client import get_llm_client

from .constants import SUPPORTED_LANGUAGES, TRANSLATION_MODEL

logger = structlog.get_logger(__name__)


def translate_text(text: str, target_language: str, user_distinct_id: str | None = None) -> str:
    """
    Translate text to target language using the LLM gateway.

    Args:
        text: The text to translate
        target_language: Target language code (e.g., 'en', 'es', 'fr')
        user_distinct_id: The user's distinct_id for analytics attribution

    Returns:
        Translated text
    """
    client = get_llm_client("llma_translation")

    target_name = SUPPORTED_LANGUAGES.get(target_language, target_language)

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
        timeout=30.0,
        user=user_distinct_id or "llma-translation",
    )

    content = response.choices[0].message.content
    return content.strip() if content else ""
