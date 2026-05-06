"""Utilities for extracting and formatting LLM messages from event properties."""

import json
from typing import Any, Union


def extract_text_from_messages(messages: Union[str, list, dict, None]) -> str:
    """
    Extract readable text from LLM message structures.

    Handles common message formats from various LLM providers:
    - OpenAI: [{"role": "user", "content": "text"}]
    - OpenAI tool calling: assistant messages with `tool_calls` (rendered alongside any content),
      paired with `role: "tool"` results that carry a `tool_call_id` for correlation
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
                rendered_msg = _render_message(msg)
                if rendered_msg is not None:
                    formatted_parts.append(rendered_msg)
            elif isinstance(msg, str):
                formatted_parts.append(msg)

        return "\n".join(formatted_parts)

    # Handle single dict message. Unlike the list path, this returns body only
    # (no `role:` prefix) — callers use it to unwrap a single message into raw
    # text rather than to render a transcript.
    if isinstance(messages, dict):
        content = messages.get("content", "")
        text = _extract_content_text(content)
        tool_calls_text = _format_tool_calls(messages.get("tool_calls"))
        return " ".join(part for part in (text, tool_calls_text) if part)

    return ""


def _render_message(msg: dict) -> str | None:
    """Render a single message dict into a `role: body` line.

    Returns None when the message has neither a role nor any body to render
    (so the caller can skip it).
    """
    role = msg.get("role", "")
    content = msg.get("content", "")
    text = _extract_content_text(content)
    tool_calls_text = _format_tool_calls(msg.get("tool_calls"))

    rendered = " ".join(part for part in (text, tool_calls_text) if part)

    # Surface tool_call_id on `role: "tool"` results so the judge can correlate
    # a tool's output with the assistant call that produced it. Without this,
    # multi-tool agentic flows lose the call/result pairing entirely.
    role_label = role
    if role == "tool":
        tool_call_id = msg.get("tool_call_id")
        if tool_call_id:
            role_label = f"tool[{tool_call_id}]"

    if rendered:
        return f"{role_label}: {rendered}" if role_label else rendered
    if role_label:
        # Preserve the conversation slot when a message has a role
        # but no body (e.g. a tool that returned nothing).
        return f"{role_label}:"
    return None


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

    The call id is included so a downstream `role: "tool"` result rendered as
    `tool[<id>]:` can be paired back to the call that produced it.
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
        call_id = tc.get("id")
        prefix = f"tool_call {call_id}" if call_id else "tool_call"
        parts.append(f"[{prefix}: {name}({args})]")
    return " ".join(parts)


def format_tool_definitions(tools: Any) -> str:
    """Render the `$ai_tools` property (the tool catalog available to the agent)
    into a compact, judge-readable summary.

    For evaluating agentic behavior, the judge often needs to know not just
    which tools were called but which tools were *callable*. A prompt like
    "did the agent pick the right tool?" is unanswerable without that catalog.

    Accepts the OpenAI-style `[{"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}]`
    shape, the Anthropic `[{"name": ..., "description": ..., "input_schema": {...}}]`
    shape, and falls back to JSON-stringifying anything unrecognized rather than
    silently dropping it.
    """
    if not tools:
        return ""

    if isinstance(tools, str):
        return tools

    if isinstance(tools, dict):
        # A bare dict is either a single tool spec (has `function` or `name`)
        # or a `{tool_name: tool_spec, ...}` mapping — flatten the latter into
        # a list of specs, carrying the mapping key over as the tool's name
        # when the value itself doesn't declare one.
        if "function" in tools or "name" in tools:
            tools = [tools]
        else:
            tools = [
                {**spec, "name": spec.get("name") or key} if isinstance(spec, dict) else spec
                for key, spec in tools.items()
            ]

    if not isinstance(tools, list):
        return json.dumps(tools, default=str)

    parts: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            parts.append(str(tool))
            continue
        # Gemini wraps multiple tools in `functionDeclarations`; expand them so
        # each declared function gets its own line in the catalog.
        declarations = tool.get("functionDeclarations")
        tools_to_render = declarations if isinstance(declarations, list) else [tool]
        for entry in tools_to_render:
            if not isinstance(entry, dict):
                parts.append(str(entry))
                continue
            rendered = _format_single_tool_definition(entry)
            if rendered:
                parts.append(rendered)
    return "\n".join(parts)


def _format_single_tool_definition(tool: dict) -> str:
    # OpenAI nests the spec under `function`; Anthropic / Gemini-unwrapped lay
    # it out at the top level. Pull from either, falling back to the tool dict
    # itself so the lookups below find name/description regardless of nesting.
    fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
    name = fn.get("name") or tool.get("name") or ""
    description = fn.get("description") or tool.get("description") or ""
    # Schema lives under different keys across providers: `parameters` for OpenAI
    # function-calling and Gemini, `input_schema` for Anthropic, and `inputSchema`
    # for the camelCase OpenAI Responses API variant.
    parameters = fn.get("parameters") or tool.get("input_schema") or tool.get("inputSchema")

    if not name:
        # Unrecognized shape — stringify so the judge still sees something.
        return json.dumps(tool, default=str)

    line = f"- {name}"
    if description:
        line += f": {description}"
    params_summary = _compact_params(parameters)
    if params_summary:
        line += f" ({params_summary})"
    return line


def _compact_params(parameters: Any) -> str:
    """Summarise a JSON-schema-style `parameters` block as `arg1, arg2?, arg3`.

    Tool catalogs can be large — dumping the full schema for every tool can
    push the judge prompt over context limits. For evaluating "did the agent
    call the right tool with the right info?", the parameter *names* (and
    which are optional) are usually all the judge needs.
    """
    if not isinstance(parameters, dict):
        return ""
    properties = parameters.get("properties")
    if not isinstance(properties, dict) or not properties:
        return ""
    required = parameters.get("required") or []
    required_set = set(required) if isinstance(required, list) else set()
    return ", ".join(key if key in required_set else f"{key}?" for key in properties)
