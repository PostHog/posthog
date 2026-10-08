import json


def flatten_parts_message(msg: dict) -> list[dict]:
    """Convert an OTel GenAI semconv parts-shaped message into flat chat message(s).

    `/i/v0/ai/otel` stores `gen_ai.input.messages` / `gen_ai.output.messages` verbatim,
    so messages arrive as `{"role": ..., "parts": [...]}` with the text inside typed
    parts instead of a flat `content` key. The judge's `message_utils._render_message`
    and the trace text formatter only read `content` and `tool_calls`, so without this
    these messages render as a bare role line and the LLM judge grades an empty
    conversation.

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
    array still reaches the JSON-stringify fallback in `message_utils._render_message`.

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
