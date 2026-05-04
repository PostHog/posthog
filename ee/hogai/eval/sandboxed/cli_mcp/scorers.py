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
* ``RecoveredToCorrectTool`` — when prompted to use a wrong tool name
  (deprecated or typo'd), did the agent end up calling a correct
  replacement?
* ``DrilledIntoSchema`` — did the agent drill into every named field
  via ``schema <tool> <field>`` before the final ``call``?
* ``PreferredSearchOverTools`` — did the agent prefer ``search`` over
  the bare ``tools`` listing for discovery?
* ``InfoBeforeCall`` — was every successful call to the target tool
  preceded by ``info <tool>`` in the same run?
* ``VerifiedEventBeforeQuery`` — did the agent run ``read-data-schema``
  before any successful ``query-*`` call?
"""

from __future__ import annotations

from typing import Literal

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import EXEC_TOOL_NAME, INFO_SYNTHETIC_PREFIX, LogParser, ToolCall

__all__ = [
    "CalledTargetTool",
    "DrilledIntoSchema",
    "InfoBeforeCall",
    "PreferredExecForm",
    "PreferredSearchOverTools",
    "RanPythonPostProcessing",
    "RecoveredToCorrectTool",
    "UsedJsonOutputFormat",
    "VerifiedEventBeforeQuery",
]


def _read_tool(expected: dict | None, scorer_name: str) -> str | None:
    """Look up ``expected[scorer_name]["tool"]`` with permissive validation."""
    if not isinstance(expected, dict):
        return None
    spec = expected.get(scorer_name)
    if not isinstance(spec, dict):
        return None
    target = spec.get("tool")
    return target if isinstance(target, str) and target else None


def _read_spec(expected: dict | None, scorer_name: str) -> dict | None:
    """Look up the per-scorer params dict ``expected[scorer_name]`` (any shape)."""
    if not isinstance(expected, dict):
        return None
    spec = expected.get(scorer_name)
    return spec if isinstance(spec, dict) else None


def _exec_command_head(call: ToolCall) -> tuple[str, str]:
    """Return ``(verb, rest)`` for a raw ``exec`` call's command string.

    Empty tuple for non-``exec`` or already-unwrapped calls. Lets scorers
    inspect the ``search`` / ``schema`` / ``tools`` verbs that
    ``_parse_exec_command`` intentionally drops on the floor.
    """
    if call.is_exec_unwrapped or call.name != EXEC_TOOL_NAME:
        return ("", "")
    cmd = call.input.get("command", "")
    if not isinstance(cmd, str):
        return ("", "")
    head, _, rest = cmd.strip().partition(" ")
    return (head.lower(), rest.strip())


def _build_parser(output: dict | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")


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


def _attempted_tool(call: ToolCall, wrong: str) -> bool:
    """True if a tool call represents an attempt against the ``wrong`` name.

    Counts (a) successful or failed unwrapped calls whose inner name matches,
    (b) ``info <wrong>`` synthetic entries, and (c) raw ``exec`` calls whose
    ``call <wrong>`` / ``info <wrong>`` command targets ``wrong`` but didn't
    parse cleanly enough to unwrap.
    """
    if call.name == wrong:
        return True
    if call.name == f"{INFO_SYNTHETIC_PREFIX}{wrong}":
        return True
    head, rest = _exec_command_head(call)
    if head not in ("call", "info"):
        return False
    if head == "call" and rest.startswith("--json"):
        rest = rest[len("--json") :].lstrip()
    target, _, _ = rest.partition(" ")
    return target.strip() == wrong


class RecoveredToCorrectTool(Scorer):
    """Binary: prompted with a wrong tool name, did the agent recover?

    ``expected = {"recovered_to_correct_tool":
        {"wrong": "query-run", "correct_any_of": ["query-trends", "execute-sql"]}}``

    Score 1.0 if the agent both *attempted* the wrong tool AND eventually made
    a successful unwrapped call to one of ``correct_any_of``. 0.0 if attempted
    but never recovered. ``None`` if ``wrong`` was never attempted (the case
    didn't actually exercise the redirect path).
    """

    def _name(self) -> str:
        return "recovered_to_correct_tool"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        spec = _read_spec(expected, self._name())
        if not spec:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        wrong = spec.get("wrong")
        correct_any_of = spec.get("correct_any_of")
        if not isinstance(wrong, str) or not wrong:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'wrong' on spec"})
        if not isinstance(correct_any_of, list) or not correct_any_of:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'correct_any_of' on spec"})
        correct_set = {c for c in correct_any_of if isinstance(c, str) and c}

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        calls = parser.get_tool_calls()
        attempted = any(_attempted_tool(call, wrong) for call in calls)
        if not attempted:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"Wrong tool '{wrong}' was never attempted", "wrong": wrong},
            )

        for call in calls:
            if call.is_error:
                continue
            if call.name in correct_set:
                return Score(
                    name=self._name(),
                    score=1.0,
                    metadata={"wrong": wrong, "recovered_to": call.name, "call_id": call.call_id},
                )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "Wrong tool attempted but no successful call to a correct replacement",
                "wrong": wrong,
                "correct_any_of": sorted(correct_set),
            },
        )


class DrilledIntoSchema(Scorer):
    """Binary: did the agent drill into every named field via ``schema <tool> <field>``?

    ``expected = {"drilled_into_schema":
        {"tool": "query-trends", "fields": ["series", "breakdownFilter"]}}``

    Looks for raw ``exec`` calls whose ``command`` is ``schema <tool> <field>``
    or ``schema <tool> <field>.<sub>`` (dot-notation prefix counts). Score 1.0
    only if every required field was drilled, 0.0 otherwise with the missing
    fields in metadata. ``None`` if the spec is malformed.
    """

    def _name(self) -> str:
        return "drilled_into_schema"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        spec = _read_spec(expected, self._name())
        if not spec:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        tool = spec.get("tool")
        fields = spec.get("fields")
        if not isinstance(tool, str) or not tool:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'tool' on spec"})
        if not isinstance(fields, list) or not fields:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'fields' on spec"})
        required = [f for f in fields if isinstance(f, str) and f]

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        drilled: set[str] = set()
        for call in parser.get_tool_calls():
            head, rest = _exec_command_head(call)
            if head != "schema":
                continue
            schema_tool, _, field_path = rest.partition(" ")
            if schema_tool.strip() != tool:
                continue
            field_path = field_path.strip()
            if not field_path:
                continue
            top_field, _, _ = field_path.partition(".")
            top_field = top_field.strip()
            if top_field in required:
                drilled.add(top_field)

        missing = [f for f in required if f not in drilled]
        if missing:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "Required fields were not drilled via 'schema'",
                    "tool": tool,
                    "missing_fields": missing,
                    "drilled_fields": sorted(drilled),
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"tool": tool, "drilled_fields": sorted(drilled)},
        )


class PreferredSearchOverTools(Scorer):
    """Binary: did the agent prefer ``search`` over the bare ``tools`` listing?

    Opt-in via presence of ``expected = {"preferred_search_over_tools": {}}``.

    Walks raw ``exec`` calls in chronological order. Score 1.0 if the first
    discovery action (``search`` or ``tools``) was ``search``, or if ``tools``
    was never used. 0.0 if ``tools`` came first or if ``tools`` was used
    without any ``search`` in the run. ``None`` if no discovery actions at all.
    """

    def _name(self) -> str:
        return "preferred_search_over_tools"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        if _read_spec(expected, self._name()) is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} key on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        calls_by_position = sorted(parser.get_tool_calls(), key=lambda c: c.position)
        first_discovery: str | None = None
        used_search = False
        used_tools = False
        for call in calls_by_position:
            head, _ = _exec_command_head(call)
            if head not in ("search", "tools"):
                continue
            if first_discovery is None:
                first_discovery = head
            if head == "search":
                used_search = True
            else:
                used_tools = True

        if first_discovery is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No discovery actions"})
        if not used_tools:
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"first_discovery": first_discovery, "used_tools": False},
            )
        if first_discovery == "search":
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"first_discovery": "search", "used_tools": True, "used_search": used_search},
            )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "Bare 'tools' was the first discovery action",
                "first_discovery": "tools",
                "used_search": used_search,
            },
        )


class InfoBeforeCall(Scorer):
    """Binary: was every successful call to the target tool preceded by ``info <tool>``?

    ``expected = {"info_before_call": {"tool": "dashboard-create"}}``

    Walks tool calls in chronological order; for each successful unwrapped
    call to ``tool``, requires that an ``info <tool>`` synthetic entry
    appeared earlier. Score 1.0 if all qualifying calls were preceded, 0.0
    otherwise. ``None`` if ``tool`` was never called successfully (caught
    upstream by ``CalledTargetTool``).
    """

    def _name(self) -> str:
        return "info_before_call"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        target = _read_tool(expected, self._name())
        if not target:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()}.tool on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        calls = sorted(parser.get_tool_calls(), key=lambda c: c.position)
        info_synthetic = f"{INFO_SYNTHETIC_PREFIX}{target}"
        seen_info = False
        offenders: list[str] = []
        successful_calls = 0
        for call in calls:
            if call.name == info_synthetic and not call.is_error:
                seen_info = True
                continue
            if call.is_exec_unwrapped and call.name == target and not call.is_error:
                successful_calls += 1
                if not seen_info:
                    offenders.append(call.call_id)

        if successful_calls == 0:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"Target '{target}' never called successfully", "tool": target},
            )
        if offenders:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "At least one call to target was not preceded by 'info <tool>'",
                    "tool": target,
                    "offenders": offenders,
                    "total_calls": successful_calls,
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"tool": target, "total_calls": successful_calls},
        )


class VerifiedEventBeforeQuery(Scorer):
    """Binary: did the agent run ``read-data-schema`` before any successful ``query_tool`` call?

    ``expected = {"verified_event_before_query": {"query_tool": "query-trends"}}``

    For each successful unwrapped call to ``query_tool``, requires that a
    successful ``read-data-schema`` call appeared earlier. Score 1.0 if all
    qualifying calls were preceded, 0.0 otherwise. ``None`` if ``query_tool``
    never called successfully.
    """

    SCHEMA_TOOL = "read-data-schema"

    def _name(self) -> str:
        return "verified_event_before_query"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        spec = _read_spec(expected, self._name())
        if not spec:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        query_tool = spec.get("query_tool")
        if not isinstance(query_tool, str) or not query_tool:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'query_tool' on spec"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        calls = sorted(parser.get_tool_calls(), key=lambda c: c.position)
        seen_schema = False
        offenders: list[str] = []
        successful_calls = 0
        for call in calls:
            if call.is_error:
                continue
            if call.is_exec_unwrapped and call.name == self.SCHEMA_TOOL:
                seen_schema = True
                continue
            if call.is_exec_unwrapped and call.name == query_tool:
                successful_calls += 1
                if not seen_schema:
                    offenders.append(call.call_id)

        if successful_calls == 0:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"Query tool '{query_tool}' never called successfully"},
            )
        if offenders:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": f"'{query_tool}' was called without a prior successful '{self.SCHEMA_TOOL}'",
                    "query_tool": query_tool,
                    "offenders": offenders,
                    "total_calls": successful_calls,
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"query_tool": query_tool, "total_calls": successful_calls},
        )


class UsedJsonOutputFormat(Scorer):
    """Binary: did the agent request raw JSON output for the named tool?

    ``expected = {"used_json_output_format": {"tool": "dashboards-get-all"}}``

    For every successful unwrapped call to ``tool``, requires
    ``requested_output_format == "json"``. The default is ``"optimized"``,
    which is fine for human-facing answers but lossy / token-truncated for
    Python post-processing — opting into ``"json"`` is the right move when
    the agent plans to parse results programmatically.

    Score 1.0 if at least one successful call to ``tool`` requested
    ``output_format == "json"``. 0.0 if every successful call used the
    default. ``None`` if the tool was never called successfully.
    """

    def _name(self) -> str:
        return "used_json_output_format"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        target = _read_tool(expected, self._name())
        if not target:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()}.tool on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        relevant = [call for call in parser.get_tool_calls(target) if not call.is_error and call.is_exec_unwrapped]
        if not relevant:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"No successful exec-unwrapped '{target}' calls", "tool": target},
            )

        json_calls = [call for call in relevant if call.requested_output_format == "json"]
        if json_calls:
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"tool": target, "json_calls": len(json_calls), "total_calls": len(relevant)},
            )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": f"All successful '{target}' calls used the default output format",
                "tool": target,
                "total_calls": len(relevant),
                "formats_seen": sorted({call.requested_output_format or "default" for call in relevant}),
            },
        )


class RanPythonPostProcessing(Scorer):
    """Binary: did the agent actually run Python to post-process tool results?

    Opt-in via presence of ``expected = {"ran_python_post_processing": {}}``.

    Walks ``Bash`` tool calls and looks for one whose command contains
    ``python`` or ``python3`` (heuristic — matches ``python -c '...'``,
    ``python3 script.py``, ``cat ... | python3 -``, ``uv run python ...``).
    Score 1.0 if any successful Bash call ran Python, 0.0 otherwise.
    ``None`` if no Bash calls at all.
    """

    PYTHON_TOKENS: frozenset[str] = frozenset({"python", "python3"})

    def _name(self) -> str:
        return "ran_python_post_processing"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        if _read_spec(expected, self._name()) is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} key on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        bash_calls = parser.get_tool_calls("Bash")
        if not bash_calls:
            return Score(name=self._name(), score=None, metadata={"reason": "No Bash calls"})

        for call in bash_calls:
            if call.is_error:
                continue
            cmd = call.input.get("command", "")
            if not isinstance(cmd, str):
                continue
            tokens = {part.split("/")[-1] for part in cmd.split() if part}
            if tokens & self.PYTHON_TOKENS:
                return Score(
                    name=self._name(),
                    score=1.0,
                    metadata={"matched_call_id": call.call_id},
                )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "No Bash call invoked python/python3",
                "bash_call_count": len(bash_calls),
            },
        )
