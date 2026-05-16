"""Accumulate ACP session/update events into structured ``ThreadMessage`` rows.

The sandbox stream delivers JSON-RPC notifications with method ``session/update``
and one of these ``sessionUpdate`` types:

- ``agent_message_chunk`` — streaming assistant text
- ``agent_thought_chunk`` — streaming reasoning text
- ``tool_call`` — initial tool-call payload (title, kind, raw_input)
- ``tool_call_update`` — status / output updates for an in-progress tool call

This module merges those events into the same ``AssistantMessage`` /
``AssistantToolCallMessage`` / ``ReasoningMessage`` shapes that the LangGraph
path persists, so ``Conversation.messages_json`` ends up as a single source of
truth that the standard ``ConversationSerializer.get_messages`` can serve.

The accumulator is single-threaded and stateful — feed one event at a time via
``feed(event)`` and call ``finalize()`` once the turn ends.
"""

from __future__ import annotations

import uuid
from typing import Any

from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage, ReasoningMessage

from ee.hogai.sandbox.types import (
    ACP_METHOD_SESSION_UPDATE,
    ACP_NOTIFICATION_TYPE,
    ACP_SESSION_UPDATE_AGENT_MESSAGE_CHUNK,
)

AGENT_THOUGHT_CHUNK = "agent_thought_chunk"
TOOL_CALL = "tool_call"
TOOL_CALL_UPDATE = "tool_call_update"


def _extract_text_content(content: Any) -> str | None:
    """Pull text out of an ACP ``content`` field, regardless of shape.

    ACP emits the field as a single ``{"type": "text", "text": "..."}`` object
    for agent message / thought chunks, and as a list of those objects for
    tool-call output. Return the concatenated text or ``None``.
    """
    if isinstance(content, dict) and content.get("type") == "text":
        text = content.get("text")
        return text if isinstance(text, str) and text else None
    if isinstance(content, list):
        parts: list[str] = []
        for entry in content:
            if isinstance(entry, dict) and entry.get("type") == "text":
                text = entry.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "".join(parts) or None
    return None


class _ToolCallBuilder:
    """Accumulates tool_call + tool_call_update notifications for one call."""

    def __init__(self, tool_call_id: str, name: str) -> None:
        self.tool_call_id = tool_call_id
        self.name = name
        self.args: dict[str, Any] = {}
        self.status: str = "pending"
        self.output_text: str = ""
        self.raw_output: Any = None

    def apply(self, update: dict[str, Any]) -> None:
        raw_input = update.get("rawInput") or update.get("raw_input")
        if isinstance(raw_input, dict):
            self.args.update(raw_input)
        title = update.get("title")
        if isinstance(title, str) and not self.name:
            self.name = title
        status = update.get("status")
        if isinstance(status, str):
            self.status = status
        # Collect output text from content[].text where present.
        content = update.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        self.output_text += text
        raw_output = update.get("rawOutput") or update.get("raw_output")
        if raw_output is not None:
            self.raw_output = raw_output


class SandboxTurnBuilder:
    """Builds the list of ``ThreadMessage`` dicts produced during one sandbox turn.

    Usage::

        builder = SandboxTurnBuilder()
        for event in stream:
            builder.feed(event)
        messages = builder.finalize()
    """

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []
        # Buffer for streaming assistant text — flushed when a different event
        # type arrives (tool call, thinking, end-of-turn).
        self._assistant_buffer: str = ""
        self._assistant_id: str | None = None
        self._thought_buffer: str = ""
        self._thought_id: str | None = None
        self._tool_builders: dict[str, _ToolCallBuilder] = {}
        # Preserve emission order of tool calls so we can interleave them with
        # buffered assistant text correctly.
        self._tool_emit_order: list[str] = []

    # ------------------------------------------------------------------ feed

    def feed(self, event: dict[str, Any]) -> None:
        if event.get("type") != ACP_NOTIFICATION_TYPE:
            return
        raw = event.get("notification")
        if not isinstance(raw, dict):
            return
        if raw.get("method") != ACP_METHOD_SESSION_UPDATE:
            return
        params = raw.get("params")
        if not isinstance(params, dict):
            return
        update = params.get("update")
        if not isinstance(update, dict):
            return

        kind = update.get("sessionUpdate")
        content_text = _extract_text_content(update.get("content"))

        if kind == ACP_SESSION_UPDATE_AGENT_MESSAGE_CHUNK:
            if content_text:
                self._flush_thought()
                if self._assistant_id is None:
                    self._assistant_id = f"sandbox-{uuid.uuid4()}"
                self._assistant_buffer += content_text
            return

        if kind == AGENT_THOUGHT_CHUNK:
            if content_text:
                self._flush_assistant()
                if self._thought_id is None:
                    self._thought_id = f"sandbox-{uuid.uuid4()}"
                self._thought_buffer += content_text
            return

        if kind in {TOOL_CALL, TOOL_CALL_UPDATE}:
            self._flush_assistant()
            self._flush_thought()
            tool_call_id = update.get("toolCallId") or update.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                return
            builder = self._tool_builders.get(tool_call_id)
            if builder is None:
                name = update.get("title") or update.get("toolName") or update.get("tool_name") or "unknown_tool"
                if not isinstance(name, str):
                    name = "unknown_tool"
                builder = _ToolCallBuilder(tool_call_id=tool_call_id, name=name)
                self._tool_builders[tool_call_id] = builder
                self._tool_emit_order.append(tool_call_id)
            builder.apply(update)
            return

    # -------------------------------------------------------------- finalize

    def finalize(self) -> list[dict[str, Any]]:
        """Flush any in-flight buffers and return the accumulated messages.

        The output preserves emission order: assistant text and reasoning are
        emitted at the point they were buffered; tool calls are emitted at
        their first-seen position. Each entry is a dict matching one of the
        ``ThreadMessage`` pydantic models, ready to write into
        ``Conversation.messages_json``.
        """
        self._flush_assistant()
        self._flush_thought()
        # Append any tool calls (and their tool-result messages) at the end if
        # we haven't already woven them inline. We emit them after the final
        # flushes so the assistant text and reasoning appear in order, then the
        # tool results follow with stable IDs the frontend can dedupe against.
        for tool_id in self._tool_emit_order:
            builder = self._tool_builders.get(tool_id)
            if builder is None:
                continue
            already_emitted = any(
                item.get("type") == "tool" and item.get("tool_call_id") == tool_id for item in self._items
            )
            if already_emitted:
                continue
            tool_message = AssistantToolCallMessage(
                content=builder.output_text or "",
                tool_call_id=tool_id,
                id=f"sandbox-tool-{tool_id}",
                # ``_sandbox: True`` distinguishes MCP tool calls (sandbox path)
                # from LangGraph contextual-tool calls so the frontend renderer
                # can pick the right component.
                ui_payload={
                    "_sandbox": True,
                    "name": builder.name,
                    "status": builder.status,
                    "args": builder.args,
                    "output": builder.raw_output if builder.raw_output is not None else builder.output_text,
                },
            )
            self._items.append(tool_message.model_dump(exclude_none=True))
        return list(self._items)

    # ------------------------------------------------------------- internals

    def _flush_assistant(self) -> None:
        if not self._assistant_buffer:
            return
        # Attach any tool calls that finished between the previous flush and now,
        # so the AssistantMessage carries them like the LangGraph path does.
        pending_tool_calls = [
            AssistantToolCall(args=builder.args, id=tool_id, name=builder.name)
            for tool_id, builder in self._tool_builders.items()
            if not any(item.get("tool_call_id") == tool_id for item in self._items)
        ]
        message = AssistantMessage(
            content=self._assistant_buffer,
            id=self._assistant_id,
            tool_calls=pending_tool_calls or None,
        )
        self._items.append(message.model_dump(exclude_none=True))
        self._assistant_buffer = ""
        self._assistant_id = None

    def _flush_thought(self) -> None:
        if not self._thought_buffer:
            return
        reasoning = ReasoningMessage(content=self._thought_buffer, id=self._thought_id)
        self._items.append(reasoning.model_dump(exclude_none=True))
        self._thought_buffer = ""
        self._thought_id = None


def build_human_message(content: str, message_id: str | None = None) -> dict[str, Any]:
    """Return a HumanMessage dict with a stable id, suitable for messages_json."""
    return HumanMessage(content=content, id=message_id or str(uuid.uuid4())).model_dump(exclude_none=True)


__all__ = ["SandboxTurnBuilder", "build_human_message"]
