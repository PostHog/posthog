"""Utilities for extracting and formatting LLM messages from event properties."""

import json
from typing import Any, Union


def extract_text_from_messages(messages: Union[str, list, dict, None]) -> str:
    """
    Extract readable text from LLM message structures.

    Handles common message formats from various LLM providers:
    - OpenAI: [{"role": "user", "content": "text"}]
    - OpenAI tool calling: assistant messages with `tool_calls` (rendered alongside any content)
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

                # Extract text from content and any OpenAI-style tool_calls
                text = _extract_content_text(content)
                tool_calls_text = _format_tool_calls(msg.get("tool_calls"))

                rendered = " ".join(part for part in (text, tool_calls_text) if part)
                if rendered:
                    formatted_parts.append(f"{role}: {rendered}" if role else rendered)
                elif role:
                    # Preserve the conversation slot when a message has a role
                    # but no body (e.g. a tool that returned nothing).
                    formatted_parts.append(f"{role}:")
            elif isinstance(msg, str):
                formatted_parts.append(msg)

        return "\n".join(formatted_parts)

    # Handle single dict message
    if isinstance(messages, dict):
        content = messages.get("content", "")
        text = _extract_content_text(content)
        tool_calls_text = _format_tool_calls(messages.get("tool_calls"))
        return " ".join(part for part in (text, tool_calls_text) if part)


def _extract_content_text(content: Union[str, list, dict, None]) -> str:
    """Extract text from message content, handling nested structures.

    Handles multiple provider formats:
    - Anthropic: [{"type": "text", "text": "..."}]
    - OpenAI Responses API: [{"text": "...", "annotations": [...]}]
    - Generic: [{"content": "..."}]
    - Plain strings

    Always falls back to str() rather than returning empty — an LLM judge
    can work with messy JSON, but not with an empty string.
    """
    if not content:
        return ""

    # Simple string content
    if isinstance(content, str):
        return content

    # Array of content blocks
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if "text" in block:
                    text_parts.append(str(block["text"]))
                elif "content" in block:
                    text_parts.append(str(block["content"]))
                else:
                    # Unknown block shape — stringify rather than silently drop
                    text_parts.append(str(block))
            elif isinstance(block, str):
                text_parts.append(block)
        return " ".join(text_parts)

    # Fallback: convert to string
    return str(content)


def _format_tool_calls(tool_calls: Any) -> str:
    """Render OpenAI-style assistant `tool_calls` into a readable string.

    Tool calls live at the message level rather than inside content blocks, so a
    naive flatten that only reads `role` and `content` drops them. Without this,
    assistant messages that *only* invoke a tool (content is null) disappear
    from the formatted conversation entirely, leaving an LLM judge unable to
    see what the agent actually did.
    """
    if not isinstance(tool_calls, list):
        return ""
    parts: list[str] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function", {})
        if not isinstance(fn, dict):
            continue
        name = fn.get("name") or ""
        if not name:
            continue
        args = fn.get("arguments", "")
        if not isinstance(args, str):
            args = json.dumps(args, default=str)
        parts.append(f"[tool_call: {name}({args})]")
    return " ".join(parts)
