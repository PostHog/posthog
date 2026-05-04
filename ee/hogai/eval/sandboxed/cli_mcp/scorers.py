"""Deterministic scorers for the cli_mcp evals.

Each case carries its per-scorer params under the scorer's ``_name()``
in ``expected``, mirroring the convention used by
``LookupIdInOutput`` (see ``retrieval/scorers.py``):

    expected = {
        "called_target_tool": {"tool": "notebooks-create"},
        "preferred_exec_form_structured": {"tool": "notebooks-create"},
    }

Scorers default to ``score=None`` when their key is missing —
unrelated cases don't drag the rollup down.

* ``CalledTargetTool`` — did the agent successfully invoke
  ``expected[<scorer_name>]["tool"]`` at least once? Returns 1.0/0.0.
* ``PreferredExecForm`` — for the named tool, did every successful
  exec-mediated call use the preferred form? ``prefer="structured"``
  requires the structured ``input`` field; ``prefer="either"`` accepts
  inline JSON or structured input. Reads the ``used_structured_input``
  flag set by ``log_parser.py`` when it sees the wire-level ``input``
  sibling.
"""

from __future__ import annotations

from typing import Literal

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser

__all__ = ["CalledTargetTool", "PreferredExecForm"]


def _read_tool(expected: dict | None, scorer_name: str) -> str | None:
    """Look up ``expected[scorer_name]["tool"]`` with permissive validation."""
    if not isinstance(expected, dict):
        return None
    spec = expected.get(scorer_name)
    if not isinstance(spec, dict):
        return None
    target = spec.get("tool")
    return target if isinstance(target, str) and target else None


class CalledTargetTool(Scorer):
    """Binary: did the agent successfully invoke ``expected[<scorer_name>]["tool"]``?"""

    def _name(self) -> str:
        return "called_target_tool"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        target = _read_tool(expected, self._name())
        if not target:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"No {self._name()}.tool on case"},
            )
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")
        for call in parser.get_tool_calls(target):
            if not call.is_error:
                return Score(name=self._name(), score=1.0, metadata={"tool": target, "call_id": call.call_id})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": f"Tool '{target}' was never successfully called", "tool": target},
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
        target = _read_tool(expected, self._name())
        if not target:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"No {self._name()}.tool on case"},
            )
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")
        relevant = [call for call in parser.get_tool_calls(target) if not call.is_error and call.is_exec_unwrapped]
        if not relevant:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"No successful exec-unwrapped '{target}' calls", "tool": target},
            )

        if self.prefer == "either":
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"tool": target, "prefer": "either", "total_calls": len(relevant)},
            )

        offenders = [call.call_id for call in relevant if not call.used_structured_input]
        if offenders:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "At least one call used inline JSON instead of the structured 'input' field",
                    "tool": target,
                    "prefer": "structured",
                    "offenders": offenders,
                    "total_calls": len(relevant),
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"tool": target, "prefer": "structured", "total_calls": len(relevant)},
        )
