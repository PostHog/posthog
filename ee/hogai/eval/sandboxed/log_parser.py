"""Unified log accessor for sandboxed-eval scorers.

Wraps :func:`acp_log.parse_log` with a typed accessor API so scorers can ask
first-class questions ("was skill X called?", "give me every call to tool X
with input + result") instead of re-walking the flat message list with
ad-hoc helpers.

Pure data layer — no Braintrust, PostHog, or model dependency. Same
contract as ``acp_log`` so this is exercised by the same lightweight unit
test config.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from .acp_log import parse_log

SKILL_TOOL_NAME = "Skill"
EXEC_TOOL_NAME = "exec"
INFO_SYNTHETIC_PREFIX = "__info__:"
"""Synthetic name assigned when ``exec {command: "info <tool>"}`` is unwrapped.

Lets scorers treat the single-exec CLI's ``info <tool>`` and Claude Code's
``ToolSearch(select:mcp__posthog__<tool>)`` as interchangeable
"tool schema loaded" signals via a stable namespaced name.
"""


def normalize_tool_name(name: str | None) -> str:
    """Strip the Claude-Code MCP namespace prefix from a tool name.

    Claude Code surfaces MCP tools as ``mcp__<server>__<tool>``. Scorers
    think in bare tool names like ``query-retention``; normalising here
    keeps the public API simple.
    """
    if not name:
        return ""
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[2]
    return name


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    """Normalized tool name. ``mcp__x__y`` → ``y``; ``exec`` is unwrapped to the
    inner tool when the command shape is recognised (see ``is_exec_unwrapped``)."""

    input: dict[str, Any]
    """Tool input arguments. For unwrapped exec calls this is the parsed JSON
    payload from ``call <tool> <json>``."""

    output: str
    """Tool result content as a string. Dict outputs are ``json.dumps``-ed
    upstream by the ACP parser."""

    is_error: bool
    """True when the paired ``tool_result`` had ``is_error: true`` OR when no
    result was captured (unpaired tool_use)."""

    call_id: str
    position: int
    """Index of the enclosing assistant message in the flat message list —
    preserves chronological order across calls."""

    raw_name: str
    """Tool name before normalisation / exec-unwrapping (the on-the-wire name)."""

    is_exec_unwrapped: bool
    """True when this entry was synthesised from an ``exec`` call's command."""


class SkillCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    """Skill name extracted from the ``Skill`` tool's ``input.skill`` field."""

    args: str | None = None
    """Optional ``input.args`` string."""

    call_id: str
    output: str
    is_error: bool
    position: int


class LogParser:
    """Public log accessor for scorers, built from raw ACP JSONL.

    Internally delegates to :func:`acp_log.parse_log` and indexes the
    resulting flat message list. Cheap to construct repeatedly per scorer
    if needed — most scorers will hold one instance.
    """

    def __init__(self, raw_log: str, *, initial_prompt: str = "") -> None:
        self._parsed = parse_log(raw_log, initial_prompt=initial_prompt)
        self._messages = self._parsed.messages
        self._initial_prompt = initial_prompt
        self._tool_results = _index_tool_results(self._messages)
        self._tool_use_positions = _index_tool_use_positions(self._messages)

    def was_skill_called(self, name: str) -> bool:
        return any(call.name == name for call in self._iter_skill_calls())

    def get_skill_calls(self, name: str | None = None) -> list[SkillCall]:
        return [call for call in self._iter_skill_calls() if name is None or call.name == name]

    def get_tool_calls(self, name: str | None = None) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for tool_use, position in self._iter_tool_uses():
            raw_name = str(tool_use.get("name") or "")
            if raw_name == SKILL_TOOL_NAME:
                continue
            normalized = normalize_tool_name(raw_name)
            tool_input = tool_use.get("input")
            if not isinstance(tool_input, dict):
                tool_input = {}
            tool_call = self._build_tool_call(
                tool_use=tool_use,
                raw_name=raw_name,
                normalized=normalized,
                tool_input=tool_input,
                position=position,
            )
            if name is None or tool_call.name == name:
                calls.append(tool_call)
        return calls

    def get_final_agent_message(self) -> str | None:
        for msg in reversed(self._messages):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            texts = [
                block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
            ]
            joined = "\n".join(t for t in texts if t)
            if joined:
                return joined
        return None

    def get_user_prompt(self) -> str:
        for msg in self._messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            return text
        return self._initial_prompt

    def _iter_skill_calls(self) -> list[SkillCall]:
        calls: list[SkillCall] = []
        for tool_use, position in self._iter_tool_uses():
            if tool_use.get("name") != SKILL_TOOL_NAME:
                continue
            tool_input = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
            assert isinstance(tool_input, dict)
            skill_name = tool_input.get("skill")
            if not isinstance(skill_name, str) or not skill_name:
                continue
            args = tool_input.get("args")
            args_str = args if isinstance(args, str) else None
            call_id = str(tool_use.get("id") or "")
            output, is_error = self._lookup_result(call_id)
            calls.append(
                SkillCall(
                    name=skill_name,
                    args=args_str,
                    call_id=call_id,
                    output=output,
                    is_error=is_error,
                    position=position,
                )
            )
        return calls

    def _iter_tool_uses(self):
        for idx, msg in enumerate(self._messages):
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    yield block, idx

    def _build_tool_call(
        self,
        *,
        tool_use: dict[str, Any],
        raw_name: str,
        normalized: str,
        tool_input: dict[str, Any],
        position: int,
    ) -> ToolCall:
        call_id = str(tool_use.get("id") or "")
        if normalized == EXEC_TOOL_NAME:
            command = tool_input.get("command", "")
            if isinstance(command, str):
                unwrapped = _parse_exec_command(command)
                if unwrapped is not None:
                    inner_name, inner_input = unwrapped
                    output, is_error = self._lookup_result(call_id)
                    return ToolCall(
                        name=inner_name,
                        input=inner_input,
                        output=output,
                        is_error=is_error,
                        call_id=call_id,
                        position=position,
                        raw_name=raw_name,
                        is_exec_unwrapped=True,
                    )
        output, is_error = self._lookup_result(call_id)
        return ToolCall(
            name=normalized,
            input=tool_input,
            output=output,
            is_error=is_error,
            call_id=call_id,
            position=position,
            raw_name=raw_name,
            is_exec_unwrapped=False,
        )

    def _lookup_result(self, call_id: str) -> tuple[str, bool]:
        if not call_id:
            return ("", True)
        result = self._tool_results.get(call_id)
        if result is None:
            return ("", True)
        content = result.get("content")
        output = content if isinstance(content, str) else (json.dumps(content) if content is not None else "")
        return (output, bool(result.get("is_error", False)))


def _index_tool_results(messages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_result":
                continue
            call_id = block.get("tool_use_id")
            if isinstance(call_id, str) and call_id:
                by_id[call_id] = block
    return by_id


def _index_tool_use_positions(messages: list[dict[str, Any]]) -> dict[str, int]:
    positions: dict[str, int] = {}
    for idx, msg in enumerate(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                call_id = block.get("id")
                if isinstance(call_id, str) and call_id and call_id not in positions:
                    positions[call_id] = idx
    return positions


def _parse_exec_command(command: str) -> tuple[str, dict[str, Any]] | None:
    """Split a CLI-style ``exec`` command string into ``(virtual_name, input)``.

    Recognised shapes (produced by single-exec mode where the agent talks to
    the PostHog MCP through one ``exec`` tool):
      - ``"info <tool>"``                    → ``("__info__:<tool>", {})``
      - ``"call [--json] <tool> <json>"``    → ``("<tool>", parsed_json)``

    Returns ``None`` for anything else (``search``, ``tools``, ``schema``,
    malformed) so callers can fall through to the raw ``exec`` representation.
    """
    stripped = command.strip()
    if not stripped:
        return None

    head, _, rest = stripped.partition(" ")
    head = head.lower()

    if head == "info":
        tool = rest.strip().split(None, 1)[0] if rest.strip() else ""
        if tool:
            return (f"{INFO_SYNTHETIC_PREFIX}{tool}", {})
        return None

    if head == "call":
        rest = rest.strip()
        if rest.startswith("--json"):
            rest = rest[len("--json") :].lstrip()
        if not rest:
            return None
        tool, _, json_part = rest.partition(" ")
        tool = tool.strip()
        if not tool:
            return None
        json_part = json_part.strip()
        parsed: dict[str, Any] = {}
        if json_part:
            try:
                decoded = json.loads(json_part)
                if isinstance(decoded, dict):
                    parsed = decoded
            except json.JSONDecodeError:
                parsed = {}
        return (tool, parsed)

    return None
