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
    - OTel GenAI semconv: [{"role": "user", "parts": [{"type": "text", "content": "..."}]}]
      as ingested verbatim from `gen_ai.input.messages` / `gen_ai.output.messages`
      by `/i/v0/ai/otel` (e.g. Vercel AI SDK spans)
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
                for flattened in _flatten_parts_message(msg):
                    rendered_msg = _render_message(flattened)
                    if rendered_msg is not None:
                        formatted_parts.append(rendered_msg)
            elif isinstance(msg, str):
                formatted_parts.append(msg)

        return "\n".join(formatted_parts)

    # Handle single dict message — render it the same way as a one-element
    # list so that role prefixes and tool_call_id correlation are surfaced
    # consistently regardless of the wrapper shape.
    rendered_messages = [_render_message(flattened) for flattened in _flatten_parts_message(messages)]
    return "\n".join(rendered for rendered in rendered_messages if rendered is not None)


def _flatten_parts_message(msg: dict) -> list[dict]:
    """Convert an OTel GenAI semconv parts-shaped message into flat chat message(s).

    `/i/v0/ai/otel` stores `gen_ai.input.messages` / `gen_ai.output.messages` verbatim,
    so messages arrive as `{"role": ..., "parts": [...]}` with the text inside typed
    parts instead of a flat `content` key. `_render_message` only reads `content` and
    `tool_calls`, which made these messages render as a bare `role:` line and left the
    LLM judge grading an empty conversation.

    Mirrors the trace UI's `otel.yaml` normalizer recipe so the judge sees the same
    conversation the trace view renders:
    - `{"type": "text", "content": ...}` parts join into the message's `content`
    - `{"type": "tool_call", "id", "name", "arguments"}` parts become `tool_calls`,
      and so do `server_tool_call` parts (provider-executed tools like web_search),
      with the polymorphic `server_tool_call` payload as the arguments
    - each `{"type": "tool_call_response", "id", "response"}` part becomes its own
      follow-up `role: "tool"` message so the existing `tool[<id>]:` correlation applies.
      `response` is the field the GenAI semconv schema requires. The spec's own example
      showed `result` for its first ten months, so producers that followed the example
      are in the wild too, and all of `response`/`result`/`server_tool_call_response`
      are read in that order, which also folds `server_tool_call_response` parts in
    - `reasoning` parts become follow-up `role: "thinking"` messages
    - `blob`/`uri`/`file` parts become bracketed text markers (`[image]`,
      `[image: <uri>]`, `[file: <id>]`). The trace view renders image blobs and uris
      as actual images; the judge gets markers instead because base64 payloads are
      token noise to an LLM
    - `compaction` parts become follow-up messages carrying the compacted summary,
      or a `[conversation compacted]` marker when the summary is absent

    Like the recipe, this only applies to dicts with a string `role` alongside the
    `parts` list, so a structured-output payload that happens to have its own `parts`
    array still reaches the JSON-stringify fallback in `_render_message`.

    Messages that already carry `content` or `tool_calls`, or have no `parts` list,
    pass through unchanged.
    """
    parts = msg.get("parts")
    if not isinstance(msg.get("role"), str) or not isinstance(parts, list):
        return [msg]
    if msg.get("content") or msg.get("tool_calls"):
        return [msg]

    text_chunks: list[str] = []
    tool_calls: list[dict] = []
    followups: list[dict] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text":
            content = part.get("content")
            if isinstance(content, str) and content:
                text_chunks.append(content)
        elif part_type in ("tool_call", "server_tool_call"):
            arguments_key = "arguments" if part_type == "tool_call" else "server_tool_call"
            tool_calls.append(
                {
                    "id": part.get("id"),
                    "function": {"name": part.get("name", ""), "arguments": part.get(arguments_key, "")},
                }
            )
        elif part_type in ("tool_call_response", "server_tool_call_response"):
            tool_response = next(
                (part[key] for key in ("response", "result", "server_tool_call_response") if part.get(key) is not None),
                "",
            )
            if not isinstance(tool_response, str):
                tool_response = json.dumps(tool_response, default=str)
            followups.append({"role": "tool", "content": tool_response, "tool_call_id": part.get("id")})
        elif part_type == "reasoning":
            reasoning = part.get("content")
            if isinstance(reasoning, str) and reasoning:
                followups.append({"role": "thinking", "content": reasoning})
        elif part_type in ("blob", "uri", "file"):
            followups.append({"role": msg["role"], "content": _media_part_marker(part_type, part)})
        elif part_type == "compaction":
            summary = part.get("content")
            if not (isinstance(summary, str) and summary):
                summary = "[conversation compacted]"
            followups.append({"role": msg["role"], "content": summary})

    primary = {key: value for key, value in msg.items() if key != "parts"}
    if text_chunks:
        primary["content"] = " ".join(text_chunks)
    if tool_calls:
        primary["tool_calls"] = tool_calls

    # Keep an empty primary only when there are no follow-up messages, so a
    # message whose parts produce nothing still holds its `role:` conversation slot
    # (matching how empty flat messages render) without adding a stray blank line
    # in front of every follow-up.
    flattened: list[dict] = []
    if text_chunks or tool_calls or not followups:
        flattened.append(primary)
    flattened.extend(followups)
    return flattened


def _media_part_marker(part_type: str, part: dict) -> str:
    modality = part.get("modality")
    if not isinstance(modality, str) or not modality:
        modality = "media"
    if part_type == "blob":
        return f"[{modality}]"
    if part_type == "uri":
        uri = part.get("uri")
        return f"[{modality}: {uri}]" if isinstance(uri, str) and uri else f"[{modality}]"
    file_id = part.get("file_id")
    return f"[file: {file_id}]" if isinstance(file_id, str) and file_id else "[file]"


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
    # Dict carries data but doesn't match the chat-message shape — most often
    # a manually-captured structured-output payload like `{"entities": [...]}`.
    # JSON-stringify so the judge sees the actual response instead of an empty
    # `Output:`. Truly-empty dicts still return None so the caller can skip them.
    if msg:
        return json.dumps(msg, default=str)
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
        # A bare dict is either a single tool spec (carrying `function`,
        # `name`, or Gemini's `functionDeclarations`) or a
        # `{tool_name: tool_spec, ...}` mapping. Wrap a recognized spec in a
        # one-element list; otherwise flatten the mapping into a list of
        # specs, carrying the mapping key over as the tool's name when the
        # value itself doesn't declare one.
        if "function" in tools or "name" in tools or "functionDeclarations" in tools:
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
    # it out at the top level. Read from the nested dict when present, falling
    # back to the top-level tool dict for each individual field.
    fn_raw = tool.get("function")
    fn: dict = fn_raw if isinstance(fn_raw, dict) else {}
    name = fn.get("name") or tool.get("name") or ""
    description = fn.get("description") or tool.get("description") or ""
    # Schema lives under different keys across providers: `parameters` for OpenAI
    # function-calling and Gemini, `input_schema` for Anthropic, and `inputSchema`
    # for the camelCase OpenAI Responses API variant.
    parameters = fn.get("parameters") or tool.get("parameters") or tool.get("input_schema") or tool.get("inputSchema")

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
