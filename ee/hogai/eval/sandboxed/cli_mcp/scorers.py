"""Deterministic scorers for the cli_mcp evals.

Each case carries its target tool name in ``expected["target_tool"]``;
both scorers read it from there so a single scorer instance handles
every case correctly without fan-out.

* ``CalledTargetTool`` — did the agent successfully invoke the case's
  target tool at least once? Returns 1.0/0.0; ``None`` if the case has
  no ``target_tool`` (misconfiguration).
* ``PreferredExecForm`` — for cases where the long/quote-heavy payload
  argues for the structured ``input`` field (notebook, skill), did
  every successful exec-mediated call use it? ``prefer="either"``
  accepts inline JSON or structured input — used for short payloads
  where either form is fine. Reads the ``used_structured_input`` flag
  set by ``log_parser.py`` when it sees the wire-level ``input``
  sibling.
"""

from __future__ import annotations

from typing import Literal

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser

__all__ = ["CalledTargetTool", "PreferredExecForm"]


def _target_tool(expected: dict | None) -> str | None:
    if not isinstance(expected, dict):
        return None
    target = expected.get("target_tool")
    return target if isinstance(target, str) and target else None


class CalledTargetTool(Scorer):
    """Binary: did the agent successfully invoke ``expected["target_tool"]``?"""

    def _name(self) -> str:
        return "called_target_tool"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        target = _target_tool(expected)
        if not target:
            return Score(name=self._name(), score=None, metadata={"reason": "No target_tool on case"})
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")
        for call in parser.get_tool_calls(target):
            if not call.is_error:
                return Score(name=self._name(), score=1.0, metadata={"target_tool": target, "call_id": call.call_id})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": f"Tool '{target}' was never successfully called", "target_tool": target},
        )


class PreferredExecForm(Scorer):
    """Binary: did successful exec-mediated calls to ``expected["target_tool"]`` use the preferred form?

    ``prefer="structured"`` — every successful exec-unwrapped call must
    have ``used_structured_input == True`` (payload via the ``input``
    parameter). For long/quote-heavy payloads.

    ``prefer="either"`` — inline JSON and structured ``input`` both
    pass. For short payloads where either form is fine.

    Calls outside the single-exec path (``is_exec_unwrapped == False``)
    and failed calls are ignored — this scorer only judges the *form*
    of successful exec-mediated calls. Returns ``score=None`` when
    there are no relevant calls (already caught by ``CalledTargetTool``).
    """

    def __init__(self, *, prefer: Literal["structured", "either"], name: str | None = None):
        self.prefer = prefer
        self._label = name or f"preferred_exec_form_{prefer}"

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        target = _target_tool(expected)
        if not target:
            return Score(name=self._name(), score=None, metadata={"reason": "No target_tool on case"})
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")
        relevant = [call for call in parser.get_tool_calls(target) if not call.is_error and call.is_exec_unwrapped]
        if not relevant:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"No successful exec-unwrapped '{target}' calls", "target_tool": target},
            )

        if self.prefer == "either":
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"target_tool": target, "prefer": "either", "total_calls": len(relevant)},
            )

        offenders = [call.call_id for call in relevant if not call.used_structured_input]
        if offenders:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "At least one call used inline JSON instead of the structured 'input' field",
                    "target_tool": target,
                    "prefer": "structured",
                    "offenders": offenders,
                    "total_calls": len(relevant),
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"target_tool": target, "prefer": "structured", "total_calls": len(relevant)},
        )
