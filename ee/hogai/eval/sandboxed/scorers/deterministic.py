from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from braintrust import Score
from braintrust_core.score import Scorer


class ExitCodeZero(Scorer):
    """Binary scorer: did the agent process exit cleanly (code 0)?"""

    def _name(self) -> str:
        return "exit_code_zero"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        exit_code = output.get("exit_code", -1)
        return Score(
            name=self._name(),
            score=1.0 if exit_code == 0 else 0.0,
            metadata={"exit_code": exit_code},
        )


class NoToolCall(Scorer):
    """Binary scorer: did the agent avoid successfully calling any forbidden tool?

    Constructed with a set of tool names that must never be successfully
    invoked. Walks `output["messages"]` (the flat Anthropic message list that
    `sandboxed/base.py` produces), pairs each `tool_use` with its
    `tool_result`, and scores `0.0` if any paired result completed without
    `is_error`. Failed calls (`is_error: true`) are allowed — the model is
    free to attempt and fail.

    Typical use: sandbox hygiene — forbid MCP tools that would persist state
    outside the disposable team (e.g. `insight-create`, `insight-update`).
    """

    forbidden: frozenset[str]
    _label: str

    def __init__(self, forbidden: Iterable[str], *, name: str = "no_forbidden_tool_call"):
        self.forbidden = frozenset(forbidden)
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        messages = output.get("messages")
        if not messages:
            return Score(name=self._name(), score=None, metadata={"reason": "No parsed messages"})

        successful_calls: list[str] = [
            tool_use["name"]
            for tool_use, _ in iter_successful_tool_calls(messages)
            if normalize_tool_name(tool_use.get("name")) in self.forbidden
        ]
        if successful_calls:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"forbidden_tools_called": successful_calls},
            )
        return Score(name=self._name(), score=1.0, metadata={})


def normalize_tool_name(name: str | None) -> str:
    """Strip the Claude-Code MCP namespace prefix from a tool name.

    When Claude Code surfaces MCP tools it exposes them as ``mcp__<server>__<tool>``.
    The sandbox ACP log captures that fully-qualified name on ``tool_use`` blocks,
    but scorers (and the rest of the repo) think in bare tool names like
    ``query-retention``. Normalizing here keeps the scorer API simple — callers
    pass unprefixed names and this function handles both shapes.
    """
    if not name:
        return ""
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[2]
    return name


def iter_successful_tool_calls(messages: list[dict[str, Any]]):
    """Yield `(tool_use_block, tool_result_block)` pairs for each completed call.

    Only yields pairs where the `tool_result` does not carry `is_error: true`.
    Unpaired tool_use blocks (call made but no result captured) are skipped —
    we can't conclude success without the paired result. Shared by scorers
    that need to inspect the agent's successful MCP interactions.
    """
    result_by_id: dict[str, dict[str, Any]] = {}
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
            if call_id:
                result_by_id[call_id] = block

    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            call_id = block.get("id")
            if not call_id:
                continue
            result = result_by_id.get(call_id)
            if result is None or result.get("is_error"):
                continue
            yield block, result
