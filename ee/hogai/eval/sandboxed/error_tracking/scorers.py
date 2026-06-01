"""Scorers for the error-tracking sandboxed evals.

Three families of scorer:

* **Tool-presence** — did the agent call the expected query tool at all?
* **Filter / argument alignment** — does the input the agent passed
  match what the user asked for? Implemented as binary LLM-judge yes/no
  classifiers, mirroring ``RetentionSchemaAlignment``.
* **Ordering + ID resolution** — for drill-down prompts, did the agent
  go list → issue (→ optional events → optional recordings), and did it
  pass the correct per-case ``issueId`` for the named seeded issue?

All scorers build a single ``LogParser`` from ``output["raw_log"]`` so they
work identically in ``mcp_mode=tools`` (per-tool MCP) and ``mcp_mode=cli``
(single-``exec`` wrapper) — the parser handles exec-unwrapping.
"""

from __future__ import annotations

import re
import json
from typing import Any

from autoevals.llm import LLMClassifier
from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser, ToolCall

__all__ = [
    "BINARY_CHOICE_SCORES",
    "ERROR_TRACKING_WRITE_TOOLS",
    "EventsArgsAlignment",
    "EventsToolUsed",
    "IssueDrilldownOrder",
    "IssueInputAlignment",
    "IssueIdMatchesTarget",
    "IssuesListInputAlignment",
    "IssuesListToolUsed",
    "QUERY_ISSUE_EVENTS_TOOL",
    "QUERY_ISSUE_TOOL",
    "QUERY_ISSUES_LIST_TOOL",
    "SESSION_RECORDINGS_LIST_TOOL",
    "extract_last_query_issue_events_input",
    "extract_last_query_issue_input",
    "extract_last_query_issues_list_input",
]

# Error-tracking MCP tools that mutate state. The sandbox is disposable
# but these still hit real PSQL rows, so any successful call for a "just
# answer the question" prompt is a regression we want to catch.
ERROR_TRACKING_WRITE_TOOLS = frozenset(
    {
        "error-tracking-issues-merge-create",
        "error-tracking-issues-partial-update",
        "error-tracking-issues-split-create",
        "error-tracking-grouping-rules-create",
        "error-tracking-grouping-rules-update",
        "error-tracking-suppression-rules-create",
        "error-tracking-suppression-rules-update",
        "error-tracking-assignment-rules-create",
    }
)

QUERY_ISSUES_LIST_TOOL = "query-error-tracking-issues-list"
QUERY_ISSUE_TOOL = "query-error-tracking-issue"
QUERY_ISSUE_EVENTS_TOOL = "query-error-tracking-issue-events"
SESSION_RECORDINGS_LIST_TOOL = "query-session-recordings-list"

BINARY_CHOICE_SCORES = {"yes": 1.0, "no": 0.0}

_JUDGE_MODEL = "gpt-5.4"
_SESSION_ID_TEXT_RE = re.compile(r"""["']?\$?session_id["']?\s*[:=]\s*["']?([^"',\s}\]]+)""")
_TOON_NON_EMPTY_RESULTS_RE = re.compile(r"""(?m)^\s*results\[[1-9]\d*\](?:\{[^}]*\})?:""")


# ---------------------------------------------------------------------------
# Tool-call extraction helpers
# ---------------------------------------------------------------------------


def _parser_for(output: dict[str, Any] | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")


def _last_successful_input(parser: LogParser | None, tool_name: str) -> dict[str, Any] | None:
    """Return the input dict of the most recent successful call to ``tool_name``."""
    if parser is None:
        return None
    successful = [c for c in parser.get_tool_calls(tool_name) if not c.is_error]
    if not successful:
        return None
    raw = successful[-1].input
    return raw if isinstance(raw, dict) else None


def _successful_inputs(parser: LogParser | None, tool_name: str) -> list[dict[str, Any]]:
    if parser is None:
        return []
    return [
        call.input for call in parser.get_tool_calls(tool_name) if not call.is_error and isinstance(call.input, dict)
    ]


def _collect_session_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        session_ids: set[str] = set()
        for key, nested in value.items():
            if key in {"$session_id", "session_id"}:
                if isinstance(nested, str):
                    session_ids.add(nested)
                elif isinstance(nested, list):
                    session_ids.update(item for item in nested if isinstance(item, str))
            session_ids.update(_collect_session_ids(nested))
        return session_ids
    if isinstance(value, list):
        session_ids = set()
        for item in value:
            session_ids.update(_collect_session_ids(item))
        return session_ids
    if isinstance(value, str):
        return {
            match.group(1)
            for match in _SESSION_ID_TEXT_RE.finditer(value)
            if match.group(1) not in {"", "null", "None"}
        }
    return set()


def _session_ids_from_output(raw_output: str) -> set[str]:
    try:
        decoded = json.loads(raw_output)
    except json.JSONDecodeError:
        return {
            match.group(1)
            for match in _SESSION_ID_TEXT_RE.finditer(raw_output)
            if match.group(1) not in {"", "null", "None"}
        }
    return _collect_session_ids(decoded)


def _session_ids_from_recordings_input(tool_input: dict[str, Any]) -> set[str]:
    raw_session_ids = tool_input.get("session_ids")
    if isinstance(raw_session_ids, str):
        return {raw_session_ids}
    if isinstance(raw_session_ids, list):
        return {item for item in raw_session_ids if isinstance(item, str)}
    return set()


def _has_results_list(value: Any) -> bool:
    if isinstance(value, dict):
        results = value.get("results")
        if isinstance(results, list):
            return bool(results)
        return any(_has_results_list(nested) for nested in value.values())
    if isinstance(value, list):
        return bool(value) and any(_has_results_list(item) for item in value)
    if isinstance(value, str):
        return bool(_TOON_NON_EMPTY_RESULTS_RE.search(value))
    return False


def _query_output_has_results(raw_output: str) -> bool:
    try:
        decoded = json.loads(raw_output)
    except json.JSONDecodeError:
        return bool(_TOON_NON_EMPTY_RESULTS_RE.search(raw_output))
    return _has_results_list(decoded)


def _has_recordings_result(value: Any) -> bool:
    if isinstance(value, dict):
        if isinstance(value.get("id"), str):
            return True
        results = value.get("results")
        if isinstance(results, list):
            return bool(results)
        return any(_has_recordings_result(nested) for nested in value.values())
    if isinstance(value, list):
        return bool(value) and any(_has_recordings_result(item) for item in value)
    if isinstance(value, str):
        return _recordings_text_has_results(value)
    return False


def _recordings_text_has_results(raw_output: str) -> bool:
    return bool(
        re.search(r"""(?m)^\s*(?:id|session_id)\s*[:=]\s*["']?[^"',\s}\]]+""", raw_output)
        or _TOON_NON_EMPTY_RESULTS_RE.search(raw_output)
    )


def _recordings_output_has_results(raw_output: str) -> bool:
    try:
        decoded = json.loads(raw_output)
    except json.JSONDecodeError:
        return _recordings_text_has_results(raw_output)
    return _has_recordings_result(decoded)


def extract_last_query_issues_list_input(output: dict[str, Any] | None) -> dict[str, Any] | None:
    return _last_successful_input(_parser_for(output), QUERY_ISSUES_LIST_TOOL)


def extract_last_query_issue_input(output: dict[str, Any] | None) -> dict[str, Any] | None:
    return _last_successful_input(_parser_for(output), QUERY_ISSUE_TOOL)


def extract_last_query_issue_events_input(output: dict[str, Any] | None) -> dict[str, Any] | None:
    return _last_successful_input(_parser_for(output), QUERY_ISSUE_EVENTS_TOOL)


def _user_prompt(output: dict[str, Any] | None) -> str:
    parser = _parser_for(output)
    if parser is not None:
        return parser.get_user_prompt()
    if output:
        prompt = output.get("prompt")
        if isinstance(prompt, str):
            return prompt
    return ""


# ---------------------------------------------------------------------------
# Tool-presence
# ---------------------------------------------------------------------------


class _ToolUsedScorer(Scorer):
    """Binary deterministic floor: did the agent successfully call ``_tool_name`` at least once?

    Used as the entry-point floor for evals whose other scorers short-circuit
    with ``score=None`` when the target tool was never called — without this
    floor, an agent that never reaches the tool would pass the suite with no
    negative signal.
    """

    _tool_name: str = ""
    _empty_result_reason: str | None = None

    def __init__(self, *, name: str):
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log to parse"})
        successful_calls = [call for call in parser.get_tool_calls(self._tool_name) if not call.is_error]
        if not successful_calls:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": f"Agent never ran {self._tool_name} successfully"},
            )
        if self._empty_result_reason is None:
            return Score(name=self._name(), score=1.0, metadata={"tool": self._tool_name})
        non_empty_positions = [call.position for call in successful_calls if _query_output_has_results(call.output)]
        if not non_empty_positions:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": self._empty_result_reason,
                    "successful_call_positions": [call.position for call in successful_calls],
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"tool": self._tool_name, "non_empty_positions": non_empty_positions},
        )


class IssuesListToolUsed(_ToolUsedScorer):
    """Floor scorer for ``query-error-tracking-issues-list``.

    Entry point for "what's broken / which errors" questions. Catches the
    agent hallucinating without querying, or falling back to a generic
    SQL/HogQL workaround instead of the typed tool.
    """

    _tool_name = QUERY_ISSUES_LIST_TOOL
    _empty_result_reason = f"{QUERY_ISSUES_LIST_TOOL} returned no issues"

    def __init__(self, *, name: str = "issues_list_tool_used"):
        super().__init__(name=name)


class EventsToolUsed(_ToolUsedScorer):
    """Floor scorer for ``query-error-tracking-issue-events``.

    Required for ``eval_events_sampling.py`` so the suite can't pass when
    the agent never reaches the events tool — without this floor,
    ``EventsArgsAlignment`` and ``IssueIdMatchesTarget`` both short-circuit
    with ``score=None`` and the run produces no failing signal.
    """

    _tool_name = QUERY_ISSUE_EVENTS_TOOL
    _empty_result_reason = f"{QUERY_ISSUE_EVENTS_TOOL} returned no sampled events"

    def __init__(self, *, name: str = "events_tool_used"):
        super().__init__(name=name)


# ---------------------------------------------------------------------------
# Filter / argument alignment (LLM judge)
# ---------------------------------------------------------------------------


class _AlignmentClassifier(LLMClassifier):
    """Shared boilerplate for binary alignment classifiers.

    Subclasses provide the prompt template, the per-tool input extractor,
    and the expected-payload key on ``case.expected``. The base class
    handles the "agent never ran the tool" / "no expected provided"
    short-circuits by returning ``Score(score=None, ...)`` before
    delegating to the LLM judge — scoring uncalled tools as 0 would
    drown out signal from cases that did call the tool with a wrong
    shape.
    """

    _expected_key: str = ""

    def _extract_actual(self, output: dict[str, Any] | None) -> dict[str, Any] | None:
        raise NotImplementedError

    async def _run_eval_async(self, output, expected=None, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        try:
            return await super()._run_eval_async(prepared["output"], prepared["expected"], **kwargs)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})

    def _run_eval_sync(self, output, expected=None, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        try:
            return super()._run_eval_sync(prepared["output"], prepared["expected"], **kwargs)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})

    def _prepare(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> dict[str, Any] | Score:
        actual = self._extract_actual(output)
        if actual is None:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "Agent never ran the expected tool successfully"},
            )
        expected_payload = (expected or {}).get(self._expected_key) if isinstance(expected, dict) else None
        if not isinstance(expected_payload, dict):
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"No expected.{self._expected_key} provided"},
            )
        return {
            "output": {"actual": actual, "prompt": _user_prompt(output)},
            "expected": {"expected": expected_payload},
        }


class IssuesListInputAlignment(_AlignmentClassifier):
    """Binary yes/no: do the filters the agent passed match the user prompt?

    Reads ``expected.issues_list_input``. Treat fields the case left
    unset as "either match or sensible default is fine" so we don't
    penalize the agent for using the API's defaults.
    """

    _expected_key = "issues_list_input"

    def _extract_actual(self, output: dict[str, Any] | None) -> dict[str, Any] | None:
        return extract_last_query_issues_list_input(output)

    def __init__(self, **kwargs):
        super().__init__(
            name="issues_list_input_alignment",
            prompt_template="""
You are comparing two argument shapes for the PostHog `query-error-tracking-issues-list` MCP tool.
The ACTUAL was produced by an agent in response to USER_PROMPT. The EXPECTED is the shape we want.

Treat these fields as material when EXPECTED sets them:
- `status` — `active` / `resolved` / `suppressed` / `pending_release` / `archived` / `all`. If EXPECTED omits it, ACTUAL omitting it OR setting `active` are both fine.
- `searchQuery` — free-text search; substring/word overlap with EXPECTED is sufficient.
- `library` — exact `$lib` match.
- `release` — exact release id, version, or git commit ID.
- `fingerprint` — exact `$exception_fingerprint` match.
- `url` — substring match on `$current_url`. Treat ACTUAL as material if it contains EXPECTED's substring.
- `personId` — exact UUID.
- `user` — user/email text match.
- `filePath` — stack-frame file path text match.
- `orderBy` — when EXPECTED sets it, ACTUAL must match. Treat `occurrences` as the default when EXPECTED omits.
- `orderDirection` — only material when EXPECTED sets it.
- `dateRange.date_from` / `dateRange.date_to` — relative windows like `-7d`, `-1w`, `-30d` are acceptable when equivalent. EXPECTED omitting `dateRange` means the API default `last 7 days` is fine.
- `assignee` — type and id must match if EXPECTED sets it.

Ignore `filterTestAccounts`, `volumeResolution`, `limit`, `offset` unless EXPECTED set them explicitly. Ignore `filterGroup` when EXPECTED uses a typed equivalent (e.g. `library`).

<user_prompt>
{{output.prompt}}
</user_prompt>

<expected_input>
{{expected.expected}}
</expected_input>

<actual_input>
{{output.actual}}
</actual_input>

Does the actual input match the expected one on the material fields above? Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class IssueInputAlignment(_AlignmentClassifier):
    """Binary yes/no: do `query-error-tracking-issue` args match the prompt?"""

    _expected_key = "issue_input"

    def _extract_actual(self, output: dict[str, Any] | None) -> dict[str, Any] | None:
        return extract_last_query_issue_input(output)

    def __init__(self, **kwargs):
        super().__init__(
            name="issue_input_alignment",
            prompt_template="""
You are comparing the ACTUAL arguments an agent passed to PostHog's `query-error-tracking-issue` MCP tool against the EXPECTED shape, given the USER_PROMPT.

Material fields when EXPECTED sets them:
- `dateRange.date_from` / `dateRange.date_to` — relative windows like `-14d`, `-2w`, `-7d`, and explicit dates are acceptable when equivalent. EXPECTED omitting `dateRange` means the API default range is fine.

Ignore `issueId` for this check (covered by a separate scorer). Ignore `filterTestAccounts`, `volumeResolution`, and response-shaping fields unless EXPECTED set them.

<user_prompt>
{{output.prompt}}
</user_prompt>

<expected_input>
{{expected.expected}}
</expected_input>

<actual_input>
{{output.actual}}
</actual_input>

Does the actual issue input match the expected one on the material fields above? Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class EventsArgsAlignment(_AlignmentClassifier):
    """Binary yes/no: are `query-error-tracking-issue-events` args sane for the prompt?

    Reads ``expected.events_args``. Specifically watches:
      - ``limit`` — defaults to 1, max 20. Asking for many examples
        without prompting is wasteful.
      - ``verbosity`` — `summary` / `stack` / `raw`. `raw` should only
        appear when the user explicitly asked for raw payload data.
      - ``searchQuery`` / ``filterGroup`` — when the user described a
        narrowing filter, one of these should reflect it.
    """

    _expected_key = "events_args"

    def _extract_actual(self, output: dict[str, Any] | None) -> dict[str, Any] | None:
        calls = _successful_inputs(_parser_for(output), QUERY_ISSUE_EVENTS_TOOL)
        return {"calls": calls} if calls else None

    def _prepare(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> dict[str, Any] | Score:
        prepared = super()._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared

        expected_payload = prepared["expected"]["expected"]
        actual = prepared["output"]["actual"]
        reason = self._first_expensive_call_reason(actual["calls"], expected_payload)
        if reason is not None:
            return Score(name=self._name(), score=0.0, metadata=reason)
        return prepared

    @staticmethod
    def _expected_limit_max(expected_payload: dict[str, Any]) -> int:
        raw_limit = expected_payload.get("limit")
        if isinstance(raw_limit, int) and not isinstance(raw_limit, bool):
            return raw_limit
        if isinstance(raw_limit, str):
            if match := re.fullmatch(r"<=\s*(\d+)", raw_limit):
                return int(match.group(1))
            if match := re.fullmatch(r"between_\d+_and_(\d+)", raw_limit):
                return int(match.group(1))
        return 5

    @staticmethod
    def _input_limit(raw_limit: Any) -> int | None:
        if isinstance(raw_limit, int) and not isinstance(raw_limit, bool):
            return raw_limit
        if isinstance(raw_limit, str) and raw_limit.isdigit():
            return int(raw_limit)
        return None

    def _first_expensive_call_reason(
        self, calls: list[dict[str, Any]], expected_payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        max_limit = self._expected_limit_max(expected_payload)
        expects_raw = expected_payload.get("verbosity") == "raw"
        for index, call in enumerate(calls, start=1):
            limit = self._input_limit(call.get("limit"))
            if limit is not None and limit > max_limit:
                return {
                    "reason": f"{QUERY_ISSUE_EVENTS_TOOL} call over-fetched sampled events",
                    "call_index": index,
                    "limit": limit,
                    "max_limit": max_limit,
                }
            verbosity = call.get("verbosity")
            if isinstance(verbosity, str) and verbosity.lower() == "raw" and not expects_raw:
                return {
                    "reason": f"{QUERY_ISSUE_EVENTS_TOOL} call requested raw payload without a raw prompt",
                    "call_index": index,
                    "verbosity": verbosity,
                }
        return None

    def __init__(self, **kwargs):
        super().__init__(
            name="events_args_alignment",
            prompt_template="""
You are comparing the ACTUAL arguments an agent passed to PostHog's `query-error-tracking-issue-events` MCP tool against the EXPECTED shape, given the USER_PROMPT. ACTUAL may contain multiple successful calls; every call must be consistent with EXPECTED.

Material fields when EXPECTED sets them:
- `limit` — integer; treat as material when EXPECTED specifies a max or a range. The tool defaults `limit=1`; `limit > 5` without an explicit "show me many" prompt is wrong.
- `verbosity` — one of `summary` / `stack` / `raw`. EXPECTED sets the value the agent should pick. The special EXPECTED value `summary_or_stack` means ACTUAL may omit verbosity (tool default), set `summary`, or set `stack`; `raw` is wrong unless the prompt asks for raw / untruncated / full payload.
- `searchQuery` — substring/word overlap with EXPECTED is sufficient.
- `filterGroup` — when EXPECTED uses a `searchQuery` and ACTUAL uses an equivalent property filter (or vice versa), that's also fine.
- `dateRange.date_from` / `dateRange.date_to` — only material when EXPECTED sets them.

Ignore `issueId` for this check (covered by a separate scorer). Ignore `filterTestAccounts`, `onlyAppFrames`, `offset`, `orderDirection` unless EXPECTED set them.

<user_prompt>
{{output.prompt}}
</user_prompt>

<expected_input>
{{expected.expected}}
</expected_input>

<actual_input>
{{output.actual}}
</actual_input>

Are all actual events arguments consistent with the expected ones? Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Drill-down ordering + target ID resolution
# ---------------------------------------------------------------------------


def _resolve_target_issue(seed: Any, expected: dict[str, Any] | None) -> dict[str, Any] | None:
    """Find the seeded ``ErrorTrackingIssue`` the case is targeting.

    Resolution order:
      1. ``expected.target_issue.name`` (or ``expected.<scorer_name>.target_issue_name``)
         — explicit override the case author can set.
      2. Substring match: the seeded issue whose name appears in
         ``expected.target_issue.name`` if missing, or in the user
         prompt — used by literal-name cases like
         "Tell me the impact of the 'Checkout API timeout' error".
    """
    if not isinstance(seed, dict):
        return None
    lookups = seed.get("lookup_issues")
    if not isinstance(lookups, list) or not lookups:
        return None

    target_name = None
    if isinstance(expected, dict):
        for key in ("target_issue", "issue_id_matches_target"):
            spec = expected.get(key)
            if isinstance(spec, dict):
                candidate = spec.get("name") or spec.get("target_issue_name")
                if isinstance(candidate, str) and candidate:
                    target_name = candidate
                    break

    if target_name is not None:
        target_lower = target_name.lower()
        for lookup in lookups:
            if isinstance(lookup, dict) and isinstance(lookup.get("name"), str):
                if lookup["name"].lower() == target_lower:
                    return lookup
        return None

    return None


class IssueIdMatchesTarget(Scorer):
    """Binary deterministic: did the agent pass the right ``issueId`` to drill-down tools?

    Resolves the case's target seeded issue, then checks whether *every*
    successful ``query-error-tracking-issue`` and
    ``query-error-tracking-issue-events`` call used that issue's ID.
    Returns ``score=None`` when the case has no target configured (e.g.
    a list-only eval), and ``score=None`` when the agent never ran a
    drill-down tool — that's the ``IssueDrilldownOrder`` scorer's job to
    catch.
    """

    def __init__(self, *, name: str = "issue_id_matches_target"):
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        target = _resolve_target_issue(output.get("seed"), expected)
        if target is None:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "No target_issue configured / seeded"},
            )
        target_id = str(target.get("id", ""))
        if not target_id:
            return Score(name=self._name(), score=None, metadata={"reason": "Target issue has no id"})

        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log to parse"})

        observed: list[tuple[str, str]] = []
        for call in parser.get_tool_calls():
            if call.is_error or call.name not in {QUERY_ISSUE_TOOL, QUERY_ISSUE_EVENTS_TOOL}:
                continue
            issue_id = call.input.get("issueId") if isinstance(call.input, dict) else None
            if isinstance(issue_id, str):
                observed.append((call.name, issue_id))

        if not observed:
            return Score(
                name=self._name(),
                score=None,
                metadata={
                    "reason": "No drill-down call observed (covered by issue_drilldown_order)",
                    "target_id": target_id,
                    "target_name": target.get("name"),
                },
            )

        mismatches = [(name, issue_id) for name, issue_id in observed if issue_id != target_id]
        if mismatches:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "Drill-down used a different issueId than the named target",
                    "target_id": target_id,
                    "target_name": target.get("name"),
                    "observed": observed,
                    "mismatches": mismatches,
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={
                "target_id": target_id,
                "target_name": target.get("name"),
                "observed": observed,
            },
        )


class IssueDrilldownOrder(Scorer):
    """Binary deterministic: did the agent walk list → optional issue → events → recordings?

    Verifies the canonical drill-down flow:

    1. ``query-error-tracking-issues-list`` was called successfully.
    2. **Default-required** when ``expected.drilldown.requires_issue`` is
       omitted or true: ``query-error-tracking-issue`` was called successfully
       after step 1, and with the target issue's per-case UUID (when a target
       is configured). Cases can set ``requires_issue=False`` when list →
       events is a valid cheaper route.
    3. **Optional** when ``expected.drilldown.requires_events`` is true:
       ``query-error-tracking-issue-events`` was called after the latest
       required predecessor (the issue call when required/present, otherwise
       the list call).
    4. **Optional** when ``expected.drilldown.requires_recordings`` is
       true: ``query-session-recordings-list`` was called after step 3
       (the events response is what surfaces the ``$session_id`` values
       to feed it).

    The case can additionally set ``forbids_events`` / ``forbids_recordings``
    to catch over-fetching: detail-only prompts ("just tell me the impact"
    of an issue) shouldn't trigger the heavier sampled-events query, and
    impact-only prompts shouldn't fan out into session recordings. When
    set, a successful call to the corresponding tool fails the scorer.
    ``requires_*`` and ``forbids_*`` for the same tool are mutually
    exclusive — when both are true, ``forbids_*`` is ignored.
    """

    def __init__(self, *, name: str = "issue_drilldown_order"):
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log to parse"})

        spec = expected.get("drilldown") if isinstance(expected, dict) else None
        if not isinstance(spec, dict):
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "No expected.drilldown spec provided"},
            )
        requires_issue = bool(spec.get("requires_issue", True))
        requires_events = bool(spec.get("requires_events", False))
        requires_recordings = bool(spec.get("requires_recordings", False))
        forbids_events = bool(spec.get("forbids_events", False)) and not requires_events
        forbids_recordings = bool(spec.get("forbids_recordings", False)) and not requires_recordings

        list_pos = self._first_pos(parser, QUERY_ISSUES_LIST_TOOL)
        issue_pos = self._first_pos(parser, QUERY_ISSUE_TOOL)
        events_pos = self._first_pos(parser, QUERY_ISSUE_EVENTS_TOOL)
        recordings_pos = self._first_pos(parser, SESSION_RECORDINGS_LIST_TOOL)

        metadata: dict[str, Any] = {
            "list_pos": list_pos,
            "issue_pos": issue_pos,
            "events_pos": events_pos,
            "recordings_pos": recordings_pos,
            "requires_issue": requires_issue,
            "requires_events": requires_events,
            "requires_recordings": requires_recordings,
            "forbids_events": forbids_events,
            "forbids_recordings": forbids_recordings,
        }

        if list_pos is None:
            metadata["reason"] = f"{QUERY_ISSUES_LIST_TOOL} was never called successfully"
            return Score(name=self._name(), score=0.0, metadata=metadata)
        if requires_issue and issue_pos is None:
            metadata["reason"] = f"{QUERY_ISSUE_TOOL} was never called successfully"
            return Score(name=self._name(), score=0.0, metadata=metadata)
        if issue_pos is not None and issue_pos <= list_pos:
            metadata["reason"] = f"{QUERY_ISSUE_TOOL} did not run after {QUERY_ISSUES_LIST_TOOL}"
            return Score(name=self._name(), score=0.0, metadata=metadata)

        if requires_events:
            if events_pos is None:
                metadata["reason"] = f"{QUERY_ISSUE_EVENTS_TOOL} was never called successfully"
                return Score(name=self._name(), score=0.0, metadata=metadata)
            events_prerequisite_pos = issue_pos if issue_pos is not None else list_pos
            events_prerequisite_tool = QUERY_ISSUE_TOOL if issue_pos is not None else QUERY_ISSUES_LIST_TOOL
            events_after_prerequisite = [
                call
                for call in parser.get_tool_calls(QUERY_ISSUE_EVENTS_TOOL)
                if not call.is_error and call.position > events_prerequisite_pos
            ]
            if not events_after_prerequisite:
                metadata["reason"] = f"{QUERY_ISSUE_EVENTS_TOOL} did not run after {events_prerequisite_tool}"
                return Score(name=self._name(), score=0.0, metadata=metadata)
            event_result_positions = [
                call.position for call in events_after_prerequisite if _query_output_has_results(call.output)
            ]
            metadata["events_result_positions"] = event_result_positions
            if not event_result_positions:
                metadata["reason"] = f"{QUERY_ISSUE_EVENTS_TOOL} returned no sampled events"
                return Score(name=self._name(), score=0.0, metadata=metadata)
        elif forbids_events and events_pos is not None:
            metadata["reason"] = (
                f"{QUERY_ISSUE_EVENTS_TOOL} was called for a prompt that did not ask for sampled events"
            )
            return Score(name=self._name(), score=0.0, metadata=metadata)

        if requires_recordings:
            if recordings_pos is None:
                metadata["reason"] = f"{SESSION_RECORDINGS_LIST_TOOL} was never called successfully"
                return Score(name=self._name(), score=0.0, metadata=metadata)
            # When recordings are required, events should also have been called,
            # because that's where `$session_id`s come from. Don't enforce a
            # strict events→recordings ordering when only recordings is
            # requested without events — the agent might pull the session id
            # from a different surface.
            min_pred = (
                events_pos
                if requires_events and events_pos is not None
                else issue_pos
                if issue_pos is not None
                else list_pos
            )
            if recordings_pos <= min_pred:
                metadata["reason"] = f"{SESSION_RECORDINGS_LIST_TOOL} did not run after its prerequisite drill-down"
                return Score(name=self._name(), score=0.0, metadata=metadata)
            recordings_call = self._first_successful_call(parser, SESSION_RECORDINGS_LIST_TOOL)
            if recordings_call is None:
                metadata["reason"] = f"{SESSION_RECORDINGS_LIST_TOOL} was never called successfully"
                return Score(name=self._name(), score=0.0, metadata=metadata)
            recordings_session_ids = _session_ids_from_recordings_input(recordings_call.input)
            metadata["recordings_session_ids"] = sorted(recordings_session_ids)
            if not recordings_session_ids:
                metadata["reason"] = f"{SESSION_RECORDINGS_LIST_TOOL} did not include session_ids from sampled events"
                return Score(name=self._name(), score=0.0, metadata=metadata)
            if not _recordings_output_has_results(recordings_call.output):
                metadata["reason"] = f"{SESSION_RECORDINGS_LIST_TOOL} returned no recordings"
                return Score(name=self._name(), score=0.0, metadata=metadata)
            event_session_ids = self._event_session_ids_before(parser, recordings_pos)
            metadata["event_session_ids"] = sorted(event_session_ids)
            if not event_session_ids:
                metadata["reason"] = f"{QUERY_ISSUE_EVENTS_TOOL} output did not expose $session_id values"
                return Score(name=self._name(), score=0.0, metadata=metadata)
            unexpected_session_ids = recordings_session_ids - event_session_ids
            if unexpected_session_ids:
                metadata["reason"] = f"{SESSION_RECORDINGS_LIST_TOOL} used session_ids not returned by sampled events"
                metadata["unexpected_session_ids"] = sorted(unexpected_session_ids)
                return Score(name=self._name(), score=0.0, metadata=metadata)
        elif forbids_recordings and recordings_pos is not None:
            metadata["reason"] = (
                f"{SESSION_RECORDINGS_LIST_TOOL} was called for a prompt that did not ask for replay context"
            )
            return Score(name=self._name(), score=0.0, metadata=metadata)

        return Score(name=self._name(), score=1.0, metadata=metadata)

    @staticmethod
    def _first_pos(parser: LogParser, tool_name: str) -> int | None:
        """Earliest position of a successful call to ``tool_name``."""
        for call in parser.get_tool_calls(tool_name):
            if not call.is_error:
                return call.position
        return None

    @staticmethod
    def _first_successful_call(parser: LogParser, tool_name: str) -> ToolCall | None:
        for call in parser.get_tool_calls(tool_name):
            if not call.is_error:
                return call
        return None

    @staticmethod
    def _event_session_ids_before(parser: LogParser, position: int) -> set[str]:
        session_ids: set[str] = set()
        for call in parser.get_tool_calls(QUERY_ISSUE_EVENTS_TOOL):
            if call.is_error or call.position > position:
                continue
            session_ids.update(_session_ids_from_output(call.output))
        return session_ids
