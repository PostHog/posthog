"""
Format input and output messages for text view.

Handles formatting of LLM messages including role-based conversations, tool calls,
and content blocks. Supports multiple provider formats (OpenAI, Anthropic, etc.)
with truncation and interactive markers for frontend display.
"""

import json
import base64
from typing import Any, TypedDict

from .constants import (
    CHAT_COMPLETIONS_MESSAGE_KEYS,
    DEFAULT_TRUNCATE_BUFFER,
    MAX_RESPONSES_FIELD_CHARS,
    MAX_UNABLE_TO_PARSE_REPR_LENGTH,
    MAX_UNPARSED_DISPLAY_LENGTH,
    MISSING_REASONING_NOTE,
    MISSING_TOOL_OUTPUT_NOTE,
    MISSING_TOOLS_NOTE,
    OVERSIZED_FIELD_NOTE,
    PLAIN_TEXT_BLOCK_TYPES,
    PRESERVE_HEADER_LINES,
    RESPONSES_ITEM_METADATA_KEYS,
    RESPONSES_TOOL_CALL_TYPES,
    RESPONSES_TOOL_OUTPUT_TYPES,
    SAMPLED_VIEW_HEADER,
    SAMPLING_MAX_ITERATIONS,
    SAMPLING_REDUCTION_FACTOR,
    SPECIAL_BLOCK_TYPES,
)
from .tool_formatter import format_tools


class FormatterOptions(TypedDict, total=False):
    """Options for formatting text representations."""

    truncated: bool  # Use truncation for long content (default: True)
    truncate_buffer: int  # Chars to show at start/end (default: 1000)
    include_markers: bool  # Use interactive markers vs plain text (default: True)
    collapsed: bool  # Show full hierarchy vs summary (default: False)
    include_line_numbers: bool  # Prefix each line with line number (default: False)
    max_length: int | None  # Max output length; randomly drop lines if exceeded (default: None)


class ToolCall(TypedDict, total=False):
    """Tool call structure supporting multiple formats."""

    function: dict[str, Any]  # OpenAI format: {name, arguments}
    name: str  # LangChain format
    args: Any  # LangChain format


def add_line_numbers(text: str) -> str:
    """
    Add line numbers to each line of text in format: L001: content

    Args:
        text: Multi-line text string

    Returns:
        Text with zero-padded line numbers prefixed to each line
    """
    lines = text.split("\n")
    # Calculate padding for line numbers (e.g., L001:, L010:, L100:)
    max_line_num = len(lines)
    padding = len(str(max_line_num))

    numbered_lines = []
    for i, line in enumerate(lines, start=1):
        line_num = str(i).zfill(padding)
        numbered_lines.append(f"L{line_num}: {line}")

    return "\n".join(numbered_lines)


def reduce_by_uniform_sampling(
    text: str,
    max_length: int,
    preserve_header_lines: int = PRESERVE_HEADER_LINES,
) -> tuple[str, bool]:
    """
    Reduce text to fit within max_length by uniformly sampling lines.

    Keeps every Nth line to achieve the target size, preserving line numbers
    so gaps in the sequence indicate omitted content. A header note explains
    the sampling ratio.

    Args:
        text: Text with line numbers (L001:, L002:, etc.)
        max_length: Maximum allowed length in characters
        preserve_header_lines: Number of lines at the start to never drop

    Returns:
        Tuple of (text, was_sampled) - sampled text and whether sampling occurred
    """
    if len(text) <= max_length:
        return text, False

    lines = text.split("\n")
    total_lines = len(lines)

    # Sampling drops whole lines, so text that is oversized but has too few lines to sample (one
    # huge payload on a single line, for example) can only be cut mid-line.
    if total_lines <= preserve_header_lines:
        return text[:max_length], True

    header_lines = lines[:preserve_header_lines]
    body_lines = lines[preserve_header_lines:]

    if not body_lines:
        return text[:max_length], True

    sample_header_template_size = len(SAMPLED_VIEW_HEADER.format(percent=100, total=total_lines)) + 1

    header_text = "\n".join(header_lines)
    header_size = len(header_text) + 1 + sample_header_template_size

    available_for_body = max_length - header_size
    if available_for_body <= 0:
        return text[:max_length], True

    avg_line_length = sum(len(line) + 1 for line in body_lines) / len(body_lines)
    target_body_lines = int(available_for_body / avg_line_length)

    if target_body_lines >= len(body_lines):
        return text[:max_length], True

    target_body_lines = max(target_body_lines, 1)

    def sample_lines(target: int) -> tuple[list[str], str, str]:
        step = len(body_lines) / target
        sampled = []
        for i in range(target):
            idx = int(i * step)
            if idx < len(body_lines):
                sampled.append(body_lines[idx])
        pct = (len(sampled) / len(body_lines)) * 100
        hdr = SAMPLED_VIEW_HEADER.format(percent=pct, total=total_lines)
        result_lines = [*header_lines[:2], hdr, *header_lines[2:], *sampled]
        return sampled, hdr, "\n".join(result_lines)

    _, _, result = sample_lines(target_body_lines)

    iteration = 0
    while len(result) > max_length and iteration < SAMPLING_MAX_ITERATIONS:
        reduction_factor = max_length / len(result) * SAMPLING_REDUCTION_FACTOR
        target_body_lines = max(int(target_body_lines * reduction_factor), 1)
        _, _, result = sample_lines(target_body_lines)
        iteration += 1

    # Hard truncate as final fallback to guarantee max_length contract
    if len(result) > max_length:
        result = result[:max_length]

    return result, True


def truncate_content(content: str, options: FormatterOptions | None = None) -> tuple[list[str], bool]:
    """
    Truncate content with middle ellipsis for long text.
    Can use interactive markers (for frontend) or plain text indicators (for backend/LLM).

    Returns:
        Tuple of (lines, truncated_flag)
    """
    if options is None:
        options = {}

    should_truncate = options.get("truncated", True)  # Default: True
    max_length = options.get("truncate_buffer", DEFAULT_TRUNCATE_BUFFER)
    use_markers = options.get("include_markers", True)  # Default: True

    if not should_truncate or len(content) <= max_length:
        return ([content], False)

    half = max_length // 2
    first_part = content[:half]
    last_part = content[-half:]
    truncated_chars = len(content) - max_length

    if use_markers:
        # Frontend: encoded marker for expand/collapse UI
        middle_part = content[half:-half]
        # Base64 encode the middle part
        encoded_middle = base64.b64encode(middle_part.encode()).decode()
        marker = f"<<<TRUNCATED|{encoded_middle}|{truncated_chars}>>>"
        return ([first_part, "", marker, "", last_part], True)
    else:
        # Backend: plain text indicator for LLM context
        marker = f"\n\n... ({truncated_chars} chars truncated) ...\n\n"
        return ([first_part + marker + last_part], True)


def format_single_tool_call(name: str, args: Any) -> str:
    """Format a single tool call as a function signature."""
    # Parse args into dict if needed
    parsed_args: dict[str, Any] | None = None

    if isinstance(args, dict):
        parsed_args = args
    elif isinstance(args, str) and args:
        try:
            parsed_args = json.loads(args)
        except json.JSONDecodeError:
            # If parsing fails, will show raw string
            pass

    # Format as function call
    if parsed_args and isinstance(parsed_args, dict):
        arg_entries = list(parsed_args.items())
        if arg_entries:
            arg_strings = [f"{k}={json.dumps(v)}" for k, v in arg_entries]
            return f"{name}({', '.join(arg_strings)})"
        return f"{name}()"
    elif args:
        # Fallback for unparseable args
        return f"{name}({args})"
    return f"{name}()"


def format_tool_calls(tool_calls: list[Any]) -> list[str]:
    """Format tool calls for display.

    Typed as `list[Any]` because recorded tool calls do not always match the `ToolCall` shape;
    some SDKs write a bare string, which the loop handles rather than crashing on `.get`.
    """
    lines: list[str] = []
    lines.append(f"Tool calls: {len(tool_calls)}")

    for tc in tool_calls:
        if not isinstance(tc, dict):
            lines.append(f"  - {tc}")
            continue

        # Handle both OpenAI format (function: {name, arguments})
        # and LangChain format (name, args)
        function = tc.get("function")
        if isinstance(function, dict):
            name = function.get("name", "unknown")
            args = function.get("arguments", "")
        else:
            name = tc.get("name", "unknown")
            args = tc.get("args", "")

        lines.append(f"  - {format_single_tool_call(name, args)}")

    return lines


def extract_tool_calls_from_content(content: Any) -> list[ToolCall]:
    """Extract tool calls from content array."""
    if not isinstance(content, list):
        return []

    tool_calls: list[ToolCall] = []
    for block in content:
        match block:
            # Handle tool-call format: { type: "tool-call", function: {...} }
            # and Anthropic function format: { type: "function", function: {...} }
            case {"type": "tool-call" | "function", "function": dict() as function}:
                tool_calls.append({"function": function})

    return tool_calls


def safe_extract_text(content: Any) -> str:
    """
    Safely extract text from various content formats.
    Handles strings, dicts with 'text' key, arrays of content blocks, etc.

    Includes data preservation in error cases to aid debugging and discovery of edge cases.
    """
    try:
        if isinstance(content, str):
            return content

        if isinstance(content, dict):
            # Try common text keys
            if "text" in content:
                return str(content["text"])
            if "content" in content:
                return safe_extract_text(content["content"])
            # Fallback to JSON representation
            return json.dumps(content)

        if isinstance(content, list):
            text_parts: list[str] = []
            for i, item in enumerate(content):
                if isinstance(item, dict):
                    item_type = item.get("type")
                    # Try both "text" and "content" keys (tool_result uses "content")
                    text_value = item.get("text") or item.get("content")

                    if text_value:
                        # Add spacing between all content blocks in the array
                        if i > 0 and text_parts:
                            text_parts.append("")  # Blank line separator

                        # If we have a type that isn't already plain text, label it
                        if item_type and item_type not in PLAIN_TEXT_BLOCK_TYPES:
                            text_parts.append(f"[{item_type.upper()}]")
                            text_parts.append("")  # Blank line after label

                        text_parts.append(str(text_value))
                elif isinstance(item, str):
                    # Add spacing before string items too
                    if i > 0 and text_parts:
                        text_parts.append("")
                    text_parts.append(item)
            if text_parts:
                return "\n".join(text_parts)

        # Fallback to string representation
        data_repr = repr(content)[:MAX_UNABLE_TO_PARSE_REPR_LENGTH]
        if len(repr(content)) > MAX_UNABLE_TO_PARSE_REPR_LENGTH:
            data_repr += "..."
        return data_repr
    except Exception as e:
        # Handle any unexpected errors during extraction
        try:
            data_repr = repr(content)[:MAX_UNABLE_TO_PARSE_REPR_LENGTH]
            return data_repr
        except Exception:
            return f"[Error: {str(e)}]"


def _is_special_block(block: Any) -> bool:
    """Check if a block needs special handling (tool calls, functions, etc)."""
    if not isinstance(block, dict):
        return False

    block_type = block.get("type")
    if block_type in SPECIAL_BLOCK_TYPES:
        return True

    # Check for tool-call content format
    if "content" in block and isinstance(block["content"], dict) and "toolName" in block["content"]:
        return True

    return False


def _format_special_block(block: dict) -> str | None:
    """
    Format special blocks (tool calls, tool_use, etc).

    Returns:
        Formatted string if block was handled, None if block should be skipped.
    """
    block_type = block.get("type")

    # Handle tool-call type directly (format: {type: "tool-call", toolName, input})
    if block_type == "tool-call":
        tool_name = block.get("toolName", "unknown")
        tool_input = block.get("input", {})
        return format_single_tool_call(tool_name, tool_input)

    # Handle tool_use type (Anthropic format)
    if block_type == "tool_use":
        tool_name = block.get("name", "unknown")
        tool_input = block.get("input", {})

        # If input is empty, check for partial_json field
        if not tool_input and "partial_json" in block:
            try:
                tool_input = json.loads(block["partial_json"])
            except (json.JSONDecodeError, ValueError):
                pass

        return format_single_tool_call(tool_name, tool_input)

    # Skip function blocks as they'll be handled separately
    if block_type == "function":
        return None

    # Handle tool-call content for inline display
    if "content" in block:
        block_content = block["content"]
        if isinstance(block_content, dict) and "toolName" in block_content:
            tool_name = block_content.get("toolName", "unknown")
            args = block_content.get("args", "")
            return format_single_tool_call(tool_name, args)
        # Handle tool-result content
        elif isinstance(block_content, dict) and "result" in block_content:
            tool_name = block_content.get("toolName", "unknown")
            return f"[Tool result: {tool_name}]"

    # Block not handled by this function
    return safe_extract_text(block)


def extract_text_content(content: Any) -> str:
    """
    Extract text content from various message content formats.
    Uses safe extraction with fallback for unparseable content.

    Handles special blocks like tool calls inline for better readability.
    """
    # Handle special cases that need inline formatting (tool calls, etc)
    if isinstance(content, list):
        # Check if any blocks need special handling
        if any(_is_special_block(block) for block in content):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    formatted = _format_special_block(block)
                    if formatted is not None and formatted:
                        text_parts.append(formatted)
                # Handle non-dict items in list
                elif isinstance(block, str):
                    text_parts.append(block)

            if text_parts:
                return "\n\n".join(text_parts)

    # Use safe extraction for non-special content (handles type labels for text/reasoning/etc)
    return safe_extract_text(content)


def extract_payload_text(payload: Any) -> str:
    """Extract text from a tool payload, returning "" only when nothing was recorded.

    A falsey scalar such as `0` or `False` is a real result, so it must not collapse to "" the
    way `None` and empty containers do. Callers label the "" case as unrecorded, and a tool that
    counted zero rows would otherwise be reported as missing evidence.
    """
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list | dict | tuple) and not payload:
        # `extract_text_content`'s repr fallback would render an empty container as a literal
        # "[]" / "{}", which reads as recorded output.
        return ""
    return extract_text_content(payload)


def _is_responses_item(msg: dict[str, Any]) -> bool:
    """True for a Responses API item, which is a typed entry carrying no Chat Completions message.

    Responses items sit at the top level of the conversation array with a `type` and none of
    `role`, `content`, or `tool_calls`. Matching on that shape rather than on a list of known
    types means a built-in tool OpenAI adds later renders its fields instead of a bare header.
    Excluding `tool_calls` keeps the shape from claiming a Chat Completions message that happens
    to be keyed by `type` and carries nothing but tool calls.
    """
    item_type = msg.get("type")
    return bool(item_type) and item_type not in PLAIN_TEXT_BLOCK_TYPES and CHAT_COMPLETIONS_MESSAGE_KEYS.isdisjoint(msg)


def _format_call_signature(msg: dict[str, Any]) -> str:
    """Render a Responses item as a function signature.

    `arguments` is a JSON tool-call payload, so it parses into keyword arguments. `input` is
    freeform custom-tool text, so it goes through verbatim. Reparsing it would rewrite an input
    that happens to look like JSON.
    """
    name = str(msg.get("name") or msg.get("type") or "unknown")
    arguments = msg.get("arguments")
    if arguments is not None:
        return format_single_tool_call(name, arguments)
    return f"{name}({msg.get('input') or ''})"


def _cap_long_strings(value: Any) -> Any:
    """Replace long strings with a note of their size, recursing into containers.

    An unrecognized item's payload can be a base64 image or screenshot. `truncate_content` would
    carry the whole value in its expand marker, so the cap has to happen before the dump.
    """
    if isinstance(value, str) and len(value) > MAX_RESPONSES_FIELD_CHARS:
        return OVERSIZED_FIELD_NOTE.format(chars=len(value))
    if isinstance(value, dict):
        return {key: _cap_long_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_cap_long_strings(item) for item in value]
    return value


def _format_responses_item_fields(msg: dict[str, Any], options: FormatterOptions | None) -> list[str]:
    """Format a Responses item from its own fields, for types with no dedicated branch.

    Built-in tools each carry a different payload (`action`, `code`, `queries`, `result`), so
    render what the item holds rather than fitting every type to a function signature.
    """
    signature = _format_call_signature(msg)
    status = msg.get("status")
    parts = [f"{signature} ({status})" if status else signature]

    payload = {key: value for key, value in msg.items() if key not in RESPONSES_ITEM_METADATA_KEYS}
    if payload:
        parts.append(json.dumps(_cap_long_strings(payload), indent=2, default=str))

    lines, _ = truncate_content("\n".join(parts), options)
    return lines


def _format_responses_item(msg: dict[str, Any], options: FormatterOptions | None = None) -> list[str] | None:
    """Format one OpenAI Responses API item, or return None when the item is not one.

    Returning None lets the caller fall back to the Chat Completions `content` path. These items
    are worth special-casing because they hold their payload outside `content`, so reading
    `content` alone drops every tool call, tool result, and reasoning summary in the conversation
    while still printing its header.
    """
    item_type = msg.get("type")

    if item_type in RESPONSES_TOOL_CALL_TYPES:
        lines, _ = truncate_content(_format_call_signature(msg), options)
        return lines

    if item_type in RESPONSES_TOOL_OUTPUT_TYPES:
        output = msg.get("output")
        text = extract_payload_text(msg.get("content") if output is None else output)
        if not text:
            return [MISSING_TOOL_OUTPUT_NOTE]
        lines, _ = truncate_content(text, options)
        return lines

    if item_type == "reasoning":
        text = extract_payload_text(msg.get("summary") or msg.get("content"))
        if not text:
            # Reasoning is frequently returned encrypted, with no readable summary at all.
            return [MISSING_REASONING_NOTE]
        lines, _ = truncate_content(text, options)
        return lines

    if item_type == "additional_tools":
        # The tool catalog this item carries runs to tens of thousands of characters, so lean on
        # `format_tools` to collapse anything longer than a short list down to a count.
        return format_tools(msg.get("tools"), options) or [MISSING_TOOLS_NOTE]

    if item_type in SPECIAL_BLOCK_TYPES:
        # Anthropic and Vercel tool blocks reach this array too, and already have a renderer that
        # produces a signature rather than a field dump.
        formatted = _format_special_block(msg)
        if formatted:
            lines, _ = truncate_content(formatted, options)
            return lines

    if _is_responses_item(msg):
        return _format_responses_item_fields(msg, options)

    return None


def _extract_responses_output_items(value: Any) -> list[Any] | None:
    """Return the item list of an OpenAI Responses API response object, or None if it isn't one.

    The Responses API answers with `{"object": "response", "output": [...]}` where Chat
    Completions answers with `{"choices": [...]}`, so a formatter that only knows `choices`
    renders no model output at all.
    """
    if not isinstance(value, dict) or value.get("object") != "response":
        return None
    output = value.get("output")
    return output if isinstance(output, list) else None


def format_messages_array(messages: list[Any], options: FormatterOptions | None = None) -> list[str]:
    """
    Format an array of message objects without header.

    This is the core message formatting logic shared across formatters.
    Each message should have role/content/tool_calls structure.

    Args:
        messages: List of message dictionaries with role, content, tool_calls
        options: Formatting options (truncation, etc.)

    Returns:
        List of formatted lines (no header, starts directly with messages)
    """
    lines: list[str] = []

    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue

        # SDKs record non-string roles, which crash `.upper()`.
        role = str(msg.get("role") or msg.get("type") or "unknown")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])

        lines.append("")
        lines.append(f"[{i + 1}] {role.upper()}")
        lines.append("")

        responses_lines = _format_responses_item(msg, options)
        if responses_lines is not None:
            lines.extend(responses_lines)
        elif content:
            text_content = extract_text_content(content)
            if text_content:
                content_lines, _ = truncate_content(text_content, options)
                lines.extend(content_lines)

        if tool_calls:
            lines.append("")
            lines.extend(format_tool_calls(tool_calls))

        # Add separator between messages (but not after the last one)
        if i < len(messages) - 1:
            lines.append("")
            lines.append("-" * 80)

    return lines


def format_input_messages(ai_input: Any, options: FormatterOptions | None = None) -> list[str]:
    """Format input messages section."""
    lines: list[str] = []

    if not ai_input or (isinstance(ai_input, list) and len(ai_input) == 0):
        return lines

    lines.append("")
    lines.append("INPUT:")

    # Handle simple string input
    if isinstance(ai_input, str):
        lines.append("")
        content_lines, _ = truncate_content(ai_input, options)
        lines.extend(content_lines)
        return lines

    # Handle array of message objects
    if isinstance(ai_input, list):
        lines.extend(format_messages_array(ai_input, options))
        return lines

    # Unknown format - show raw with data preservation
    lines.append("")
    lines.append(f"[Unparsed input format: {type(ai_input).__name__}]")
    json_repr = json.dumps(ai_input)
    if len(json_repr) > MAX_UNPARSED_DISPLAY_LENGTH:
        json_repr = json_repr[:MAX_UNPARSED_DISPLAY_LENGTH] + "..."
    lines.append(json_repr)

    return lines


def format_output_messages(
    ai_output: Any, ai_output_choices: Any, options: FormatterOptions | None = None
) -> list[str]:
    """Format output messages section."""
    lines: list[str] = []

    # Responses API output (an item list) rather than Chat Completions choices. An empty item
    # list falls through, so a recorded `$ai_output` string still gets rendered below.
    responses_items = _extract_responses_output_items(ai_output_choices) or _extract_responses_output_items(ai_output)
    if responses_items:
        lines.append("")
        lines.append("OUTPUT:")
        lines.extend(format_messages_array(responses_items, options))
        return lines

    # Simple string output
    if ai_output and isinstance(ai_output, str):
        lines.append("")
        lines.append("OUTPUT:")
        lines.append("")
        content_lines, _ = truncate_content(ai_output, options)
        lines.extend(content_lines)
        return lines

    # Extract choices array if wrapped in an object (e.g., xai format: {choices: [...]})
    choices = ai_output_choices
    if ai_output_choices and isinstance(ai_output_choices, dict) and "choices" in ai_output_choices:
        if isinstance(ai_output_choices["choices"], list):
            choices = ai_output_choices["choices"]

    # Output choices (most common format)
    if choices and isinstance(choices, list) and len(choices) > 0:
        # Extract messages from choices
        messages = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue

            # The Responses API can send its items at the top level of the array, with no `role`
            # and no `content`. Pass those straight to `format_messages_array`, which knows their
            # shapes, rather than dropping them for failing the role check below.
            if _is_responses_item(choice):
                messages.append(choice)
                continue

            # Extract message from choice
            # Handle both OpenAI format (choice.message) and Anthropic format (choice is the message)
            message = choice.get("message")
            if not message or not isinstance(message, dict):
                # Anthropic/direct format - choice IS the message
                if "role" in choice or "content" in choice:
                    message = choice
                else:
                    continue

            # Normalize tool_calls - extract from content if present
            tool_calls = message.get("tool_calls", [])
            content = message.get("content", "")
            content_tool_calls = extract_tool_calls_from_content(content)
            if content_tool_calls:
                tool_calls = content_tool_calls

            # Create normalized message
            normalized_message = {
                "role": message.get("role", "assistant"),
                "content": content,
                "tool_calls": tool_calls,
            }
            messages.append(normalized_message)

        if messages:
            lines.append("")
            lines.append("OUTPUT:")
            lines.extend(format_messages_array(messages, options))

        return lines

    # Fallback - no recognizable output format
    return lines
