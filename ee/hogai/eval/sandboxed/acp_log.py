"""Parse ACP JSONL session logs into structured generations and spans.

No PostHog, Braintrust, or OpenAI dependency — this module is pure data
transformation so it can be exercised by lightweight unit tests.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationDescriptor:
    """One model turn: full conversation history → assistant response."""

    input_messages: list[dict[str, Any]] = field(default_factory=list)
    output_content: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    timestamp: str = ""
    """Timestamp of the first output block in this generation (for chronological ordering)."""

    start_ts: str = ""
    """When this model call was invoked — session prompt time for the first gen,
    the last tool_result completion time for subsequent gens."""

    end_ts: str = ""
    """Timestamp of the last output block added to this generation — approximates
    when the model's streaming response finished."""


@dataclass
class SpanDescriptor:
    span_id: str
    span_name: str
    content: str = ""
    timestamp: str = ""


@dataclass
class ParsedLog:
    generations: list[GenerationDescriptor] = field(default_factory=list)
    spans: list[SpanDescriptor] = field(default_factory=list)
    first_timestamp: str = ""
    last_timestamp: str = ""

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Flat Anthropic message list (for Braintrust compatibility).

        Uses the last generation's input (full history) plus its output
        to reconstruct the complete conversation.
        """
        if not self.generations:
            return []
        last = self.generations[-1]
        msgs = list(last.input_messages)
        if last.output_content:
            msgs.append({"role": "assistant", "content": list(last.output_content)})
        return msgs

    @property
    def total_token_usage(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for gen in self.generations:
            for k, v in gen.token_usage.items():
                total[k] = total.get(k, 0) + v
        return total


class AcpLogParser:
    """Single-use parser for an ACP JSONL session log.

    Holds all state that accumulates as the parser walks the log, dispatches
    each line to a handler method based on notification method and session
    update kind, and returns a populated ``ParsedLog``.

    Each generation represents one model API call with the full accumulated
    conversation history as input (matching how autoregressive LLMs work).
    Generation boundaries are detected when a new ``agent_message`` or
    ``tool_call`` arrives after tool results have been collected — that
    signals the model received the tool results and is producing a new
    response.
    """

    def __init__(self, initial_prompt: str = ""):
        self._result = ParsedLog()

        # Full conversation history — grows with each generation.
        # Seed with the initial prompt (not present in the ACP log).
        self._history: list[dict[str, Any]] = []
        if initial_prompt:
            self._history.append({"role": "user", "content": initial_prompt})

        # State for the current generation being built
        self._current_output: list[dict[str, Any]] = []
        self._pending_tool_results: list[dict[str, Any]] = []
        self._last_token_usage: dict[str, int] = {}
        self._gen_timestamp: str = ""
        self._gen_start_ts: str = ""  # When the model call was invoked
        self._gen_last_output_ts: str = ""  # Timestamp of most recent output block
        self._last_tool_result_ts: str = ""  # Drives next gen's start_ts

    def parse(self, raw_log: str) -> ParsedLog:
        for line in raw_log.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._handle_entry(entry)

        # Flush anything remaining (e.g. if end_turn was missing)
        self._drain_pending_tool_results_into_history()
        self._flush_generation()
        return self._result

    def _handle_entry(self, entry: dict) -> None:
        ts = entry.get("timestamp", "")
        if ts:
            if not self._result.first_timestamp:
                self._result.first_timestamp = ts
            self._result.last_timestamp = ts

        notification = entry.get("notification")
        if not isinstance(notification, dict):
            return

        # Capture the session/prompt timestamp as the start of the first model call
        # (orchestrator sends the prompt; the model starts processing it).
        method = notification.get("method", "")
        if method == "session/prompt" and ts and not self._gen_start_ts:
            self._gen_start_ts = ts

        # Token usage + end_turn completion
        entry_result = notification.get("result")
        if isinstance(entry_result, dict):
            if self._handle_result(entry_result):
                return  # end_turn consumed this entry

        if method == "_posthog/console":
            self._on_console(notification, ts)
            return
        if method == "_posthog/error":
            self._on_error(notification, ts)
            return
        if method != "session/update":
            return

        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if isinstance(update, dict):
            self._dispatch_session_update(update, ts)

    def _handle_result(self, entry_result: dict) -> bool:
        """Process token usage and end_turn. Returns True if end_turn was handled."""
        usage = entry_result.get("usage")
        if isinstance(usage, dict):
            self._last_token_usage = {
                "inputTokens": usage.get("inputTokens", 0),
                "outputTokens": usage.get("outputTokens", 0),
                "cachedReadTokens": usage.get("cachedReadTokens", 0),
                "cachedWriteTokens": usage.get("cachedWriteTokens", 0),
                "totalTokens": usage.get("totalTokens", 0),
            }
        if entry_result.get("stopReason") == "end_turn":
            self._flush_generation(token_usage=self._last_token_usage)
            self._last_token_usage = {}
            return True
        return False

    def _on_console(self, notification: dict, ts: str) -> None:
        params = notification.get("params", {}) or {}
        level = params.get("level", "info")
        msg = params.get("message", "")
        if not msg:
            return
        self._result.spans.append(
            SpanDescriptor(
                span_id=str(uuid.uuid4()),
                span_name=f"console/{level}",
                content=msg,
                timestamp=ts,
            )
        )

    def _on_error(self, notification: dict, ts: str) -> None:
        params = notification.get("params", {})
        msg = params.get("message", "") if isinstance(params, dict) else str(params)
        self._result.spans.append(
            SpanDescriptor(
                span_id=str(uuid.uuid4()),
                span_name="error",
                content=msg or "unknown error",
                timestamp=ts,
            )
        )

    def _dispatch_session_update(self, update: dict, ts: str) -> None:
        kind = update.get("sessionUpdate", "")
        handler = self._SESSION_UPDATE_HANDLERS.get(kind)
        if handler is not None:
            handler(self, update, ts)
        # Intentionally ignored: agent_message_chunk, agent_thought_chunk,
        # usage_update, available_commands_update, etc.

    def _on_user_message(self, update: dict, _ts: str) -> None:
        self._flush_generation()
        self._drain_pending_tool_results_into_history()
        text = self._extract_text(update)
        if text:
            self._history.append({"role": "user", "content": text})

    def _on_agent_message(self, update: dict, ts: str) -> None:
        # If tool results are pending, the model has received them and is
        # producing a new response — flush the previous generation first.
        self._flush_for_new_turn_if_pending()

        if not self._gen_timestamp:
            self._gen_timestamp = ts
        text = self._extract_text(update)
        if text:
            self._current_output.append({"type": "text", "text": text})
            self._gen_last_output_ts = ts

    def _on_tool_call(self, update: dict, ts: str) -> None:
        # A new tool_call with pending tool_results means the previous model call
        # finished (with just its tool_use output, no text), tools ran, and now a
        # new model call has produced this next tool_use. Flush the previous gen.
        self._flush_for_new_turn_if_pending()

        if not self._gen_timestamp:
            self._gen_timestamp = ts
        meta = update.get("_meta", {})
        cc = meta.get("claudeCode", {}) if isinstance(meta, dict) else {}
        tool_name = cc.get("toolName", update.get("title", "unknown_tool"))
        tool_call_id = update.get("toolCallId", str(uuid.uuid4()))
        raw_input = update.get("rawInput", {})

        self._current_output.append(
            {
                "type": "tool_use",
                "id": tool_call_id,
                "name": tool_name,
                "input": raw_input if isinstance(raw_input, dict) else {},
            }
        )
        self._gen_last_output_ts = ts

    def _on_tool_call_update(self, update: dict, ts: str) -> None:
        tool_call_id = update.get("toolCallId", "")

        # ACP streams the tool input in a follow-up update, not the initial tool_call.
        # Patch the matching tool_use block so $ai_output_choices carries real args.
        late_input = update.get("rawInput")
        if isinstance(late_input, dict) and late_input and tool_call_id:
            for block in self._current_output:
                if block.get("type") == "tool_use" and block.get("id") == tool_call_id:
                    block["input"] = late_input
                    break

        status = update.get("status", "")
        if status not in ("completed", "failed", "error") or not tool_call_id:
            return

        raw_output = update.get("rawOutput", "")
        content = self._extract_text(update)
        output_text = raw_output if raw_output else (content or "")
        if isinstance(output_text, dict):
            output_text = json.dumps(output_text)

        tool_result: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": str(output_text) if output_text else "(no output)",
        }
        if status in ("failed", "error"):
            tool_result["is_error"] = True
        self._pending_tool_results.append(tool_result)
        if ts:
            self._last_tool_result_ts = ts

    _SESSION_UPDATE_HANDLERS = {
        "user_message": _on_user_message,
        "agent_message": _on_agent_message,
        "tool_call": _on_tool_call,
        "tool_call_update": _on_tool_call_update,
    }

    def _flush_for_new_turn_if_pending(self) -> None:
        """If we have queued tool_results, we're starting a new model call:
        flush the previous generation, append the tool_results as a user
        message in history, and set the next generation's start_ts."""
        if not self._pending_tool_results:
            return
        self._flush_generation()
        self._history.append({"role": "user", "content": list(self._pending_tool_results)})
        self._pending_tool_results = []
        self._gen_start_ts = self._last_tool_result_ts

    def _drain_pending_tool_results_into_history(self) -> None:
        if self._pending_tool_results:
            self._history.append({"role": "user", "content": list(self._pending_tool_results)})
            self._pending_tool_results = []

    def _flush_generation(self, token_usage: dict[str, int] | None = None) -> None:
        """Flush accumulated output into a GenerationDescriptor with full history as input."""
        if not self._current_output:
            return
        self._result.generations.append(
            GenerationDescriptor(
                input_messages=list(self._history),
                output_content=list(self._current_output),
                token_usage=token_usage or {},
                timestamp=self._gen_timestamp,
                start_ts=self._gen_start_ts,
                end_ts=self._gen_last_output_ts or self._gen_timestamp,
            )
        )
        # Add the assistant response to history for the next generation
        self._history.append({"role": "assistant", "content": list(self._current_output)})
        self._current_output = []
        self._gen_timestamp = ""
        self._gen_start_ts = ""
        self._gen_last_output_ts = ""

    @staticmethod
    def _extract_text(update: dict) -> str:
        content = update.get("content")
        if isinstance(content, dict) and content.get("type") == "text":
            return content.get("text", "").strip()
        if isinstance(content, str):
            return content.strip()
        message = update.get("message")
        if isinstance(message, str):
            return message.strip()
        return ""


def parse_log(raw_log: str, initial_prompt: str = "") -> ParsedLog:
    """Parse an ACP JSONL log into per-turn generations and span descriptors.

    ``initial_prompt`` is injected as the first user message because the
    agent-server's ``sendInitialTaskMessage`` doesn't emit a ``user_message``
    session update in the ACP log.
    """
    return AcpLogParser(initial_prompt=initial_prompt).parse(raw_log)
