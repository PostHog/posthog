"""Extract user messages from $ai_input for sentiment classification."""

from typing import Union

from posthog.temporal.llm_analytics.message_utils import _extract_content_text


def extract_user_messages(ai_input: Union[str, list, dict, None]) -> str:
    """Extract and concatenate all user messages from $ai_input.

    Filters for role === "user" messages, extracts text content,
    and concatenates with "\n\n---\n\n" separator. Handles OpenAI and
    Anthropic message formats.

    Returns empty string if no user messages found, input is missing,
    or all user messages are empty.
    """
    if not ai_input:
        return ""

    if isinstance(ai_input, str):
        return ai_input

    if isinstance(ai_input, dict):
        if ai_input.get("role") == "user":
            return _extract_content_text(ai_input.get("content", ""))
        return ""

    if isinstance(ai_input, list):
        user_texts = []
        for msg in ai_input:
            if isinstance(msg, dict) and msg.get("role") == "user":
                text = _extract_content_text(msg.get("content", ""))
                if text:
                    user_texts.append(text)
        return "\n\n---\n\n".join(user_texts)

    return ""


def truncate_to_token_limit(text: str, max_chars: int = 1500) -> str:
    """Truncate text to approximate token limit.

    The cardiffnlp/twitter-roberta-base-sentiment-latest model has a
    512 token limit. We approximate with a character limit since
    average English token is ~4 characters. Using 1500 chars gives
    a safe margin below 512 tokens.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars]
