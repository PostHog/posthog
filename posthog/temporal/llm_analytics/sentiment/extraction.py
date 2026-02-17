"""Extract user messages from $ai_input for sentiment classification."""

from posthog.temporal.llm_analytics.message_utils import _extract_content_text
from posthog.temporal.llm_analytics.sentiment.constants import MAX_MESSAGE_CHARS, MAX_USER_MESSAGES


def _is_tool_result_message(content: object) -> bool:
    """Check if message content consists entirely of tool_result blocks.

    In Anthropic format, tool results are sent as user-role messages with
    content like [{"type": "tool_result", "tool_use_id": "...", "content": "..."}].
    These carry tool output, not user sentiment, so we exclude them to
    avoid noise in classification scores.
    """
    if not isinstance(content, list) or not content:
        return False
    return all(isinstance(block, dict) and block.get("type") == "tool_result" for block in content)


def extract_user_messages(ai_input: object) -> str:
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

    if not isinstance(ai_input, list):
        return ""

    user_texts = []
    for msg in ai_input:
        if isinstance(msg, dict) and msg.get("role") == "user":
            if _is_tool_result_message(msg.get("content")):
                continue
            text = _extract_content_text(msg.get("content", ""))
            if text:
                user_texts.append(text)
    return "\n\n---\n\n".join(user_texts)


def extract_user_messages_individually(ai_input: object) -> list[tuple[int, str]]:
    """Extract the last N individual user messages from $ai_input.

    Returns (original_index, text) tuples where original_index is the
    position in the $ai_input array. This index serves as a stable key
    for matching sentiment results to frontend message rendering,
    regardless of how each side normalizes/filters messages.

    Limited to the last MAX_USER_MESSAGES to bound compute.
    """
    if not ai_input:
        return []

    if isinstance(ai_input, str):
        return [(0, ai_input)] if ai_input else []

    if isinstance(ai_input, dict):
        if ai_input.get("role") == "user":
            text = _extract_content_text(ai_input.get("content", ""))
            return [(0, text)] if text else []
        return []

    if not isinstance(ai_input, list):
        return []

    result: list[tuple[int, str]] = []
    for i, msg in enumerate(ai_input):
        if isinstance(msg, dict) and msg.get("role") == "user":
            if _is_tool_result_message(msg.get("content")):
                continue
            text = _extract_content_text(msg.get("content", ""))
            if text:
                result.append((i, text))
    return result[-MAX_USER_MESSAGES:]


def truncate_to_token_limit(text: str, max_chars: int = MAX_MESSAGE_CHARS) -> str:
    """Keep the last max_chars characters of text.

    The cardiffnlp/twitter-roberta-base-sentiment-latest model has a
    512 token limit. We approximate with a character limit since
    average English token is ~4 characters. Using 2000 chars gives
    a safe margin below 512 tokens.

    Takes the tail of the text because the end of a message is
    typically more informative for sentiment.
    """
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]
