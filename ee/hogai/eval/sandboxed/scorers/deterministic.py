from __future__ import annotations

from collections.abc import Iterable

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser


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
    invoked. Walks the parsed tool-call list from ``LogParser`` and scores
    ``0.0`` if any successful (``is_error=False``) call's normalized name
    is in the forbidden set. Failed calls are allowed — the model is free
    to attempt and fail.

    Typical use: sandbox hygiene — forbid MCP tools that would persist state
    outside the disposable team (e.g. ``insight-create``, ``insight-update``).
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
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")
        successful_calls: list[str] = [
            call.name for call in parser.get_tool_calls() if not call.is_error and call.name in self.forbidden
        ]
        if successful_calls:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"forbidden_tools_called": successful_calls},
            )
        return Score(name=self._name(), score=1.0, metadata={})


class LastToolCallNot(Scorer):
    """Binary scorer: was the agent's *final* tool call not a forbidden one?

    Walks the parsed tool-call list from ``LogParser`` and inspects only the
    last successful call — scores ``0.0`` if its normalized name is in the
    forbidden set. Earlier calls (including failed ones) are ignored: the
    agent is free to explore and even hit the forbidden tool mid-run, as long
    as the final answer comes from a different tool.

    Typical use: forbid ``execute-sql`` as the closing call in product-analytics
    evals where the agent is expected to land on ``query-trends`` /
    ``query-funnel`` / ``query-retention``. Lets the agent peek at SQL during
    discovery without penalising the run, but fails it for answering via SQL.
    """

    forbidden: frozenset[str]
    _label: str

    def __init__(self, forbidden: str | Iterable[str], *, name: str = "last_tool_call_not_forbidden"):
        if isinstance(forbidden, str):
            self.forbidden = frozenset({forbidden})
        else:
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
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")
        successful = [call for call in parser.get_tool_calls() if not call.is_error]
        if not successful:
            return Score(name=self._name(), score=None, metadata={"reason": "No successful tool calls"})

        last = successful[-1]
        if last.name in self.forbidden:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"last_tool_call": last.name},
            )
        return Score(name=self._name(), score=1.0, metadata={"last_tool_call": last.name})


class RequiredToolCall(Scorer):
    """Binary scorer: did the agent successfully invoke at least one required tool?

    Constructed with a set of tool names — at least one of them must appear
    as a successful (``is_error=False``) call from ``LogParser.get_tool_calls``.
    Failed calls don't count; the model must have actually received a
    non-error result.

    Typical use: agent hygiene — require ``read-data-schema`` so the agent
    verifies an event/property exists in the team before running a query.
    """

    required: frozenset[str]
    _label: str

    def __init__(self, required: Iterable[str], *, name: str = "required_tool_call"):
        self.required = frozenset(required)
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
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")
        seen: list[str] = [
            call.name for call in parser.get_tool_calls() if not call.is_error and call.name in self.required
        ]
        if seen:
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"required_tools_called": sorted(set(seen))},
            )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": "No required tool call found", "required": sorted(self.required)},
        )
