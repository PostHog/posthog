"""Scorers for MCP eval cases."""

from __future__ import annotations

from typing import Any

from braintrust import Score
from braintrust_core.score import Scorer


class ToolCallCount(Scorer):
    """Score 1.0 if the run made between ``min_count`` and ``max_count`` tool calls (inclusive), else 0.0.

    The intent is not to enforce an exact number — agents can take a different
    valid path — but to flag runs where the model either called nothing (model
    answered without tools when it shouldn't have) or looped excessively.
    """

    def __init__(self, *, min_count: int, max_count: int):
        if min_count < 0 or max_count < min_count:
            raise ValueError(f"invalid bounds: min={min_count}, max={max_count}")
        self.min_count = min_count
        self.max_count = max_count

    def _name(self) -> str:
        return "tool_call_count"

    async def _run_eval_async(self, output: Any = None, **_: Any) -> Score:
        return self._score(output)

    def _run_eval_sync(self, output: Any = None, **_: Any) -> Score:
        return self._score(output)

    def _score(self, output: Any) -> Score:
        if output is None or not hasattr(output, "tool_calls"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "no output"})
        count = len(output.tool_calls)
        in_range = self.min_count <= count <= self.max_count
        return Score(
            name=self._name(),
            score=1.0 if in_range else 0.0,
            metadata={"count": count, "min": self.min_count, "max": self.max_count},
        )


class LatencyMs(Scorer):
    """Pure metric — always returns ``None`` so it doesn't fail runs, but logs total wall-clock latency."""

    def _name(self) -> str:
        return "latency_ms"

    async def _run_eval_async(self, output: Any = None, **_: Any) -> Score:
        return self._score(output)

    def _run_eval_sync(self, output: Any = None, **_: Any) -> Score:
        return self._score(output)

    def _score(self, output: Any) -> Score:
        if output is None or not hasattr(output, "total_latency_ms"):
            return Score(name=self._name(), score=None, metadata={"reason": "no output"})
        return Score(
            name=self._name(),
            score=None,
            metadata={"latency_ms": output.total_latency_ms},
        )
