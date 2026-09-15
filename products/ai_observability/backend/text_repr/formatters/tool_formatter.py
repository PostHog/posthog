"""
Format available tools section for text view.

Handles formatting of LLM tool/function definitions into human-readable signatures.
Supports multiple provider formats (OpenAI, Anthropic, Google/Gemini) with
automatic collapsing for long tool lists.
"""

import json
import base64
from typing import TYPE_CHECKING, Any, TypedDict

from posthog.dataclasses import frozen

from .constants import DEFAULT_TOOLS_COLLAPSE_THRESHOLD

if TYPE_CHECKING:
    from .message_formatter import FormatterOptions


class Tool(TypedDict, total=False):
    """Tool structure supporting multiple LLM provider formats."""

    type: str
    function: dict[str, Any]  # OpenAI format: {name, description, parameters}
    name: str  # Anthropic, direct formats
    description: str
    input_schema: dict[str, Any]  # Anthropic format (snake_case)
    inputSchema: dict[str, Any]  # OpenAI format (camelCase)
    functionDeclarations: list[Any]  # Google/Gemini format
    parameters: dict[str, Any]  # Google/Gemini format (unwrapped)


@frozen
class _ToolDefinition:
    """A tool reduced to the fields a signature needs, whatever provider format it came in."""

    name: str
    description: str
    parameter_schema: Any


def _unwrap_declarations(tool: dict[str, Any]) -> list[Any]:
    """Unwrap the Google/Gemini format: {functionDeclarations: [{name, description, parameters}]}."""
    declarations = tool.get("functionDeclarations")
    if isinstance(declarations, list):
        return declarations
    return [tool]


def _flatten_tools(tools_list: list[Any]) -> list[Any]:
    """Unwrap every container, so a Google/Gemini bundle counts as its tools and not as one item."""
    flattened: list[Any] = []
    for tool in tools_list:
        if isinstance(tool, dict):
            flattened.extend(_unwrap_declarations(tool))
        else:
            flattened.append(tool)
    return flattened


def _read_description(source: dict[str, Any]) -> str:
    """SDKs record non-string descriptions, which crash `.split()` in `_format_description`."""
    description = source.get("description", "N/A")
    return description if isinstance(description, str) else "N/A"


def _read_tool(tool: dict[str, Any]) -> _ToolDefinition:
    """Read name, description and parameter schema out of any supported provider format."""
    if "function" in tool and isinstance(tool["function"], dict):
        # OpenAI format: {type: 'function', function: {name, description, parameters}}
        function = tool["function"]
        return _ToolDefinition(
            name=str(function.get("name", "unknown")),
            description=_read_description(function),
            parameter_schema=function.get("parameters"),
        )

    if "name" in tool:
        # Multiple formats:
        # - Anthropic: {name, description, input_schema} (snake_case)
        # - OpenAI: {name, description, inputSchema} (camelCase)
        # - Google/Gemini unwrapped: {name, description, parameters}
        return _ToolDefinition(
            name=str(tool["name"]),
            description=_read_description(tool),
            parameter_schema=tool.get("input_schema") or tool.get("inputSchema") or tool.get("parameters"),
        )

    # Unknown format
    return _ToolDefinition(
        name=str(tool.get("type", "UNKNOWN")), description=json.dumps(tool)[:100], parameter_schema=None
    )


def _format_signature(name: str, schema: Any) -> str:
    """Build a function signature such as `read_file(path: string, lines?: string)`."""
    # SDKs record non-object `properties`, which crashes `.items()` below.
    if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
        return f"{name}()"

    # SDKs record a `required` that holds no members, which crashes the `in` test below.
    required = schema.get("required", [])
    if not isinstance(required, list | tuple | set):
        required = []

    params: list[str] = []
    for param_name, param_info in schema["properties"].items():
        if not isinstance(param_info, dict):
            continue
        param_type = param_info.get("type", "any")
        optional_marker = "" if param_name in required else "?"
        params.append(f"{param_name}{optional_marker}: {param_type}")

    return f"{name}({', '.join(params)})"


def _format_description(description: str) -> str:
    """Keep only the first line of the description, and end it with a period."""
    first_line = description.split("\n")[0]
    first_sentence = first_line.split(". ")[0]
    return first_sentence if first_sentence.endswith(".") else f"{first_sentence}."


def _format_tools_list(tools_list: list[Any]) -> str:
    """
    Format a flattened list of tools into text representation.
    Returns the formatted text as a single string.
    """
    lines: list[str] = []

    for tool in tools_list:
        # Skip non-dict entries
        if not isinstance(tool, dict):
            continue

        definition = _read_tool(tool)

        lines.append("")
        lines.append(f"  {_format_signature(definition.name, definition.parameter_schema)}")

        if definition.description and definition.description != "N/A":
            lines.append(f"    {_format_description(definition.description)}")

    return "\n".join(lines)


def format_tools(ai_tools: Any, options: "FormatterOptions | None" = None) -> list[str]:
    """
    Format available tools section.

    Supports multiple LLM provider formats:
    - OpenAI: {type: 'function', function: {name, description, parameters}}
    - Anthropic: {name, description, input_schema}
    - Google/Gemini: {functionDeclarations: [...]} or unwrapped
    - Dictionary format: {"tool_name": {name, description, ...}, ...}

    For tool lists > 5 items, creates a collapsed/expandable section by default.
    Use include_markers=False to show plain text "[+]" indicators instead.
    """
    lines: list[str] = []

    if not ai_tools:
        return lines

    # Convert dictionary format to list
    tools_list: list[Any]
    if isinstance(ai_tools, dict):
        # Handle dictionary format: {tool_name: tool_spec, ...}
        tools_list = list(ai_tools.values())
    elif isinstance(ai_tools, list):
        tools_list = ai_tools
    else:
        return lines

    # The count drives the collapse threshold, so unwrap before counting.
    tools_list = _flatten_tools(tools_list)

    if len(tools_list) == 0:
        return lines

    options = options or {}
    include_markers = options.get("include_markers", True)
    collapse_threshold: int = options.get("tools_collapse_threshold", DEFAULT_TOOLS_COLLAPSE_THRESHOLD)  # type: ignore[assignment]

    lines.append("")

    # For long tool lists (> threshold), create expandable section
    if len(tools_list) > collapse_threshold:
        display_text = f"AVAILABLE TOOLS: {len(tools_list)}"

        if include_markers:
            # Format all tools and encode for frontend to expand
            tools_content = _format_tools_list(tools_list)
            full_content = f"{display_text}\n{tools_content}"
            encoded_content = base64.b64encode(full_content.encode()).decode()
            expandable_marker = f"<<<TOOLS_EXPANDABLE|{display_text}|{encoded_content}>>>"
            lines.append(expandable_marker)
        else:
            # Plain text for backend/LLM
            lines.append(f"[+] {display_text}")

        return lines

    # For short tool lists (<= threshold), show full list
    lines.append(f"AVAILABLE TOOLS: {len(tools_list)}")
    tools_content = _format_tools_list(tools_list)
    lines.append(tools_content)

    return lines
