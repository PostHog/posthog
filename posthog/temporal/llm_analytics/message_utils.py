"""Utilities for extracting and formatting LLM messages from event properties."""

from typing import Union


def extract_text_from_messages(messages: Union[str, list, dict, None]) -> str:
    """
    Extract readable text from LLM message structures.

    Handles common message formats from various LLM providers:
    - OpenAI: [{"role": "user", "content": "text"}]
    - Anthropic: [{"role": "user", "content": [{"type": "text", "text": "..."}]}]
    - Simple strings

    Returns formatted string like:
    "user: Hello\\nassistant: Hi there"
    """
    if not messages:
        return ""

    # Handle string input
    if isinstance(messages, str):
        return messages

    # Handle list of messages
    if isinstance(messages, list):
        formatted_parts = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")

                # Extract text from content
                text = _extract_content_text(content)
                if text:
                    formatted_parts.append(f"{role}: {text}" if role else text)
            elif isinstance(msg, str):
                formatted_parts.append(msg)

        return "\n".join(formatted_parts)

    # Handle single dict message
    if isinstance(messages, dict):
        content = messages.get("content", "")
        return _extract_content_text(content)


def _extract_content_text(content: Union[str, list, dict, None]) -> str:
    """Extract text from message content, handling nested structures."""
    if not content:
        return ""

    # Simple string content
    if isinstance(content, str):
        return content

    # Array of content blocks (Anthropic format)
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                # Text block: {"type": "text", "text": "..."}
                if block.get("type") == "text" and "text" in block:
                    text_parts.append(block["text"])
                # Generic content field
                elif "content" in block:
                    text_parts.append(str(block["content"]))
            elif isinstance(block, str):
                text_parts.append(block)
        return " ".join(text_parts)

    # Fallback: convert to string
    return str(content)
