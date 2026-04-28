"""Product-analytics scorers for the sandboxed agent evals.

Each scorer extracts the final ``query-<insight>`` MCP tool call the agent
made (retention, trends, or funnel) and grades it against an expected shape
or against the user prompt. Binary outputs only — the LLM is asked yes/no.

``SchemaDiscoveryOrder`` is a deterministic scorer that asserts the agent
first loads the target MCP tool schema (via Claude Code's ``ToolSearch``
deferred-tool loader, which is what the MCP CLI's ``info <tool>`` maps to
in the sandbox), then verifies the data schema via ``read-data-schema``,
and only then runs the actual query tool.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from autoevals.llm import LLMClassifier
from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import INFO_SYNTHETIC_PREFIX, LogParser, ToolCall

QUERY_TRENDS_TOOL_NAME = "query-trends"
QUERY_RETENTION_TOOL_NAME = "query-retention"
QUERY_FUNNEL_TOOL_NAME = "query-funnel"
READ_DATA_SCHEMA_TOOL_NAME = "read-data-schema"
TOOL_SEARCH_TOOL_NAME = "ToolSearch"

BINARY_CHOICE_SCORES = {"yes": 1.0, "no": 0.0}

_JUDGE_MODEL = "gpt-5.4"

# PostHog MCP tools that persist saved-insight state. The sandbox is disposable
# but these tools still hit real rows, so any successful call is a bug in the
# agent's behaviour for a "just run the query" prompt.
INSIGHT_WRITE_TOOLS = frozenset(
    {
        "insight-create",
        "insight-update",
        "insight-partial-update",
        "insight-destroy",
    }
)


class _JudgedScorer(LLMClassifier):
    """Shared wiring for product-analytics LLM judges.

    Subclasses implement ``_prepare(output, expected)`` returning either a
    ``Score`` to short-circuit, or a dict with ``output``/``expected`` to
    forward to the LLM judge.

    Both the short-circuit paths and judge-call exceptions map to
    ``score=0.0`` rather than ``score=None`` — Braintrust treats ``None`` as
    "skipped" and drops it from the aggregate, which silently hides broken
    judges and missing query inputs. We want those to surface as failing
    scores instead.
    """

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

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        raise NotImplementedError


def _parser_for(output: dict[str, Any] | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")


def _extract_last_successful_input(parser: LogParser | None, tool_name: str) -> dict[str, Any] | None:
    if parser is None:
        return None
    successful = [c for c in parser.get_tool_calls(tool_name) if not c.is_error]
    if not successful:
        return None
    return successful[-1].input


def _user_prompt(output: dict[str, Any] | None) -> str:
    """Return the original user prompt from the eval output dict."""
    parser = _parser_for(output)
    if parser is not None:
        return parser.get_user_prompt()
    if output:
        prompt = output.get("prompt")
        if isinstance(prompt, str):
            return prompt
    return ""


def extract_last_query_retention_input(output: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the input dict of the most recent successful ``query-retention`` call.

    Returns ``None`` when the agent never ran the tool successfully — scorers
    that depend on this should short-circuit with ``score=None`` in that case
    rather than counting it as an incorrect retention query.
    """
    return _extract_last_successful_input(_parser_for(output), QUERY_RETENTION_TOOL_NAME)


class RetentionSchemaAlignment(_JudgedScorer):
    """Binary yes/no: does the retention query the agent ran match the expected one?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        actual = extract_last_query_retention_input(output)
        if actual is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran query-retention successfully"},
            )
        expected_query = (expected or {}).get("retention_query") if isinstance(expected, dict) else None
        if not isinstance(expected_query, dict):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "No expected.retention_query provided"},
            )
        return {
            "output": {"retention_query": actual},
            "expected": {"retention_query": expected_query},
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="retention_schema_alignment",
            prompt_template="""
You are comparing two retention query specs. The ACTUAL spec was produced by an agent via PostHog's `query-retention` MCP tool. The EXPECTED spec is the correct answer we want.

Treat these fields as material:
- `kind` (must be `RetentionQuery`)
- `retentionFilter.targetEntity` — type, id, and properties (if any). Event ids must match exactly (event names are case-sensitive); action ids are numeric.
- `retentionFilter.returningEntity` — same rules as targetEntity.
- `retentionFilter.period` — "Day" / "Week" / "Month" / "Hour".
- `retentionFilter.totalIntervals` — exact count of intervals.
- `dateRange.date_from` / `dateRange.date_to` — relative windows like "-14d" are acceptable when equivalent to the expected window.
- `properties` and nested `*.properties` entity-level filters — key, operator, and value must match.

Ignore `filterTestAccounts`, `retentionType`, `retentionReference`, `cumulative`, `showMean`, and `samplingFactor` unless they were set explicitly in the expected spec; those have sensible defaults that the agent may legitimately pick.

<expected_query>
{{expected.retention_query}}
</expected_query>

<actual_query>
{{output.retention_query}}
</actual_query>

Does the actual retention query match the expected retention query on the material fields above? Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class RetentionTimeRangeRelevancy(_JudgedScorer):
    """Binary yes/no: is the retention query's time range / period consistent with the user prompt?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        actual = extract_last_query_retention_input(output)
        if actual is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran query-retention successfully"},
            )
        prompt = _user_prompt(output)
        return {
            "output": {
                "retention_query": actual,
                "prompt": prompt,
            },
            "expected": expected or {},
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="retention_time_range_relevancy",
            prompt_template="""
Check the time range and cohort period of a retention query against the user's prompt.

Evaluation rules:
1. Explicit time mentions (e.g. "last 14 days", "last 3 months", "this year") — `dateRange.date_from` must be consistent (e.g. `-14d`, `-3m`, etc.).
2. Explicit period mentions — "daily" → period "Day", "weekly" → "Week", "monthly" → "Month".
3. `retentionFilter.totalIntervals` should align with the asked window (e.g. "last 14 days, daily" → roughly 14).
4. If the prompt has no time component at all, a sensible default (weekly, 11 weeks, last ~11 weeks) is fine.
5. Ignore `filterTestAccounts` and unrelated fields — they are not about time.

<user_prompt>
{{output.prompt}}
</user_prompt>

<actual_query>
{{output.retention_query}}
</actual_query>

Is the time range / period in the actual query consistent with the user's prompt? Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


def extract_last_query_trends_input(output: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the input dict of the most recent successful ``query-trends`` call.

    Returns ``None`` when the agent never ran the tool successfully — scorers
    that depend on this should short-circuit with ``score=None`` in that case
    rather than counting it as an incorrect trends query.
    """
    return _extract_last_successful_input(_parser_for(output), QUERY_TRENDS_TOOL_NAME)


class TrendsSchemaAlignment(_JudgedScorer):
    """Binary yes/no: does the trends query the agent ran match the expected one?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        actual = extract_last_query_trends_input(output)
        if actual is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran query-trends successfully"},
            )
        expected_query = (expected or {}).get("trends_query") if isinstance(expected, dict) else None
        if not isinstance(expected_query, dict):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "No expected.trends_query provided"},
            )
        return {
            "output": {"trends_query": actual},
            "expected": {"trends_query": expected_query},
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="trends_schema_alignment",
            prompt_template="""
You are comparing two trends query specs. The ACTUAL spec was produced by an agent via PostHog's `query-trends` MCP tool. The EXPECTED spec is the correct answer we want.

Treat these fields as material:
- `kind` (must be `TrendsQuery`).
- `series[]` — each series must match on:
    - `kind` (e.g. `EventsNode`, `ActionsNode`).
    - `event` — event names are case-sensitive and must match exactly. `null` is the "All events" sentinel.
    - `math` — e.g. `total`, `dau` (unique users, legacy name), `unique_session`, `avg`, `median`, `p95`, `sum`, etc.
    - `math_property` — required when the math operation needs one (e.g. `avg` of `$session_duration`).
    - `properties` — entity-level property filters; `key`, `operator`, `value`, and `type` must match. Multiple selected values may appear as arrays.
- `dateRange.date_from` / `dateRange.date_to` — relative windows like `-14d`, `-3m`, `-1y` are acceptable when equivalent to the expected window. Absolute dates must match.
- `interval` — `hour` / `day` / `week` / `month`.
- `breakdownFilter.breakdowns[]` — each breakdown's `property` and `type` must match. If expected has no breakdown, actual shouldn't introduce one.
- `trendsFilter.display` — only when it is non-default in the expected spec (e.g. `BoldNumber`, `ActionsBar`).
- `trendsFilter.formulaNodes[]` — formulas must match semantically (e.g. `A/B` vs `B/A * 100`).

Ignore `filterTestAccounts`, `samplingFactor`, `showLegend`, `showValuesOnSeries`, `smoothingIntervals`, `compareFilter`, and other cosmetic fields unless they were set explicitly in the expected spec.

<expected_query>
{{expected.trends_query}}
</expected_query>

<actual_query>
{{output.trends_query}}
</actual_query>

Does the actual trends query match the expected trends query on the material fields above? Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class TrendsTimeRangeRelevancy(_JudgedScorer):
    """Binary yes/no: is the trends query's time range / interval consistent with the user prompt?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        actual = extract_last_query_trends_input(output)
        if actual is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran query-trends successfully"},
            )
        prompt = _user_prompt(output)
        return {
            "output": {
                "trends_query": actual,
                "prompt": prompt,
            },
            "expected": expected or {},
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="trends_time_range_relevancy",
            prompt_template="""
Check the time range and interval granularity of a trends query against the user's prompt.

Evaluation rules:
1. Explicit time mentions (e.g. "last 14 days", "last 3 months", "this year", "January 2025") — `dateRange.date_from` must be consistent (`-14d`, `-3m`, an absolute `YYYY-MM-DD`, etc.). Absolute ranges must match month/year.
2. Implicit granularity mentions — "daily" → `interval: "day"`, "weekly" → `week`, "monthly" → `month`, "hourly" → `hour`.
3. If the prompt has no time component at all, a sensible default (last 30 days with `interval: "day"`) is acceptable.
4. Ignore `filterTestAccounts`, display type, breakdowns, series math, and unrelated fields — they are not about time.

<user_prompt>
{{output.prompt}}
</user_prompt>

<actual_query>
{{output.trends_query}}
</actual_query>

Is the time range / interval in the actual query consistent with the user's prompt? Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


def extract_last_query_funnel_input(output: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the input dict of the most recent successful ``query-funnel`` call.

    Returns ``None`` when the agent never ran the tool successfully — scorers
    that depend on this should short-circuit with ``score=None`` in that case
    rather than counting it as an incorrect funnel query. The agent may have
    legitimately answered via HogQL (``execute-sql``); that's covered by the
    exit-code scorer, not by these LLM judges.
    """
    return _extract_last_successful_input(_parser_for(output), QUERY_FUNNEL_TOOL_NAME)


class FunnelSchemaAlignment(_JudgedScorer):
    """Binary yes/no: does the funnel query the agent ran match the expected one?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        actual = extract_last_query_funnel_input(output)
        if actual is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran query-funnel successfully"},
            )
        expected_query = (expected or {}).get("funnel_query") if isinstance(expected, dict) else None
        if not isinstance(expected_query, dict):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "No expected.funnel_query provided"},
            )
        return {
            "output": {"funnel_query": actual},
            "expected": {"funnel_query": expected_query},
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="funnel_schema_alignment",
            prompt_template="""
You are comparing two funnel query specs. The ACTUAL spec was produced by an agent via PostHog's `query-funnel` MCP tool. The EXPECTED spec is the correct answer we want.

Treat these fields as material:
- `kind` (must be `FunnelsQuery`).
- `series` — an ORDERED array of steps. Step order is load-bearing:
    - The number of steps in `series` must match the expected count.
    - For every index `i`, the actual `series[i]` must align with the expected `series[i]` — NOT set-equality. "Both funnels contain step X" is not enough; step X must be at the same position.
    - Each step's `kind` must match (`EventsNode` vs `ActionsNode`).
    - For `EventsNode`, `event` names must match exactly (event names are case-sensitive). For `ActionsNode`, `id` (numeric) must match exactly.
    - `properties` on each step — key, operator, value, and type must match. Multi-value filters should line up regardless of list ordering.
- `series[].optionalInFunnel` — when set to `true`, marks a skippable middle step. Must match the expected shape exactly. Should never be set on the first or last step.
- `funnelsFilter.funnelOrderType` — `"ordered"` / `"unordered"` / `"strict"`. If unset in the actual, assume `"ordered"` (the schema default) and treat that as matching if expected is also unset or `"ordered"`.
- `funnelsFilter.funnelVizType` — `"steps"` / `"time_to_convert"` / `"trends"`.
- `funnelsFilter.funnelWindowInterval` + `funnelsFilter.funnelWindowIntervalUnit` — the conversion-window size (e.g. `14` + `"day"`). Must match when set in the expected spec.
- `funnelsFilter.breakdownAttributionType` / `funnelsFilter.breakdownAttributionValue` — only grade when the expected sets one.
- `funnelsFilter.exclusions` — each exclusion's `event`, `funnelFromStep`, and `funnelToStep` must match.
- `dateRange.date_from` / `dateRange.date_to` — relative windows like `-14d` or `-3m` are acceptable when equivalent to the expected window.
- `breakdownFilter.breakdown` / `breakdownFilter.breakdown_type` — only grade when the expected sets one.
- `aggregation_group_type_index` — must match when expected sets a non-null value.

Ignore `filterTestAccounts`, `samplingFactor`, `showLegend`, `binCount`, `funnelStepReference`, `funnelAggregateByHogQL`, UI-only fields, and anything else not listed above unless the EXPECTED spec sets it explicitly.

<expected_query>
{{expected.funnel_query}}
</expected_query>

<actual_query>
{{output.funnel_query}}
</actual_query>

Does the actual funnel query match the expected funnel query on the material fields above? Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class FunnelTimeRangeRelevancy(_JudgedScorer):
    """Binary yes/no: is the funnel query's time range + conversion window consistent with the user prompt?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        actual = extract_last_query_funnel_input(output)
        if actual is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran query-funnel successfully"},
            )
        prompt = _user_prompt(output)
        return {
            "output": {
                "funnel_query": actual,
                "prompt": prompt,
            },
            "expected": expected or {},
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="funnel_time_range_relevancy",
            prompt_template="""
Check the time range and conversion window of a funnel query against the user's prompt.

Funnels have two separate time concepts — evaluate them independently:
1. `dateRange.date_from` / `dateRange.date_to` — the overall window the funnel looks at. Explicit time mentions in the prompt ("in the last 30 days", "this January", "for yesterday", "from 2020 to 2025", "before 2024-01-01") must map here. Relative windows (`-14d`, `-3m`, `-1y`) are acceptable when equivalent.
2. `funnelsFilter.funnelWindowInterval` + `funnelsFilter.funnelWindowIntervalUnit` — the per-user conversion window (how long after the first step the later steps still count). This is FUNNEL-SPECIFIC. Phrases like "within 24 hours", "over a 7-day window", "convert within 2 weeks" map HERE, not to `dateRange`. Default of `14` + `"day"` is acceptable when the prompt doesn't mention a conversion window.

Other rules:
- Funnels don't have an `interval` field (that's a trends concept). Don't grade on it.
- If the prompt has no explicit overall time component at all, `-14d`/`-30d` defaults are fine.
- If the prompt has no explicit conversion-window mention, default `funnelWindowInterval=14` + `funnelWindowIntervalUnit="day"` is fine.
- Ignore `filterTestAccounts`, `funnelVizType`, `funnelOrderType`, and unrelated fields — they are not about time.

<user_prompt>
{{output.prompt}}
</user_prompt>

<actual_query>
{{output.funnel_query}}
</actual_query>

Are the time range AND the conversion window in the actual query consistent with the user's prompt? Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class SchemaDiscoveryOrder(Scorer):
    """Binary deterministic scorer: did the agent discover before querying?

    Verifies, in order, that the agent:
      1. Called ``ToolSearch`` with a query referencing the target query tool
         (the sandbox's equivalent of the CLI ``info <tool>`` command —
         Claude Code uses ``ToolSearch`` to load deferred MCP tool schemas).
      2. Successfully called ``read-data-schema`` with a matching ``kind``
         and a ``search`` substring matching the event of interest.
      3. Successfully called the query tool (e.g. ``query-trends``) only
         *after* both of the above.

    Expected shape (keyed by scorer name or the static key
    ``schema_discovery``, both accepted)::

        {
            "schema_discovery": {
                "query_tool": "query-trends",
                "data_kind": "events",
                "data_search_any_of": ["pageview", "$pageview"],
            }
        }
    """

    def __init__(self, *, name: str = "schema_discovery_order"):
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
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        spec = self._spec(expected)
        if spec is None:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "No expected.schema_discovery spec provided"},
            )

        query_tool = spec["query_tool"]
        data_kind = spec.get("data_kind")
        search_any_of = [s.lower() for s in spec.get("data_search_any_of", []) if isinstance(s, str)]

        # Successful calls only — matches the legacy "skip error results" behaviour.
        ordered = [c for c in parser.get_tool_calls() if not c.is_error]

        tool_search_pos = self._find_tool_search_pos(ordered, query_tool)
        data_schema_pos = self._find_read_data_schema_pos(ordered, data_kind, search_any_of)
        query_pos = self._find_query_tool_pos(ordered, query_tool)

        metadata: dict[str, Any] = {
            "tool_search_ok": tool_search_pos is not None,
            "data_schema_ok": data_schema_pos is not None,
            "query_tool_ok": query_pos is not None,
        }

        if query_pos is None:
            metadata["reason"] = f"{query_tool} was never called successfully"
            return Score(name=self._name(), score=0.0, metadata=metadata)
        if tool_search_pos is None:
            metadata["reason"] = f"Tool schema for {query_tool} never loaded (no ToolSearch or `info {query_tool}`)"
            return Score(name=self._name(), score=0.0, metadata=metadata)
        if data_schema_pos is None:
            metadata["reason"] = "read-data-schema never called with a matching search"
            return Score(name=self._name(), score=0.0, metadata=metadata)

        order_ok = tool_search_pos < query_pos and data_schema_pos < query_pos
        metadata["order_ok"] = order_ok
        if not order_ok:
            metadata["reason"] = "query tool ran before schema discovery steps"
            return Score(name=self._name(), score=0.0, metadata=metadata)

        return Score(name=self._name(), score=1.0, metadata=metadata)

    def _spec(self, expected: dict | None) -> dict | None:
        if not isinstance(expected, dict):
            return None
        spec = expected.get("schema_discovery") or expected.get(self._name())
        if not isinstance(spec, dict):
            return None
        if not isinstance(spec.get("query_tool"), str):
            return None
        return spec

    @staticmethod
    def _find_tool_search_pos(ordered: list[ToolCall], query_tool: str) -> int | None:
        """Match either Claude-Code's ``ToolSearch`` (per-tool MCP mode) or
        the synthetic ``__info__:<tool>`` entry emitted by single-exec's
        ``info <tool>`` command — both represent "tool schema loaded"."""
        needle = query_tool.lower()
        info_synthetic = f"{INFO_SYNTHETIC_PREFIX}{query_tool}".lower()
        for call in ordered:
            if call.name.lower() == info_synthetic:
                return call.position
            if call.name != TOOL_SEARCH_TOOL_NAME:
                continue
            raw = call.input.get("query", "")
            query = raw.lower() if isinstance(raw, str) else ""
            if needle in query:
                return call.position
        return None

    @staticmethod
    def _find_read_data_schema_pos(
        ordered: list[ToolCall],
        data_kind: str | None,
        search_any_of: Iterable[str],
    ) -> int | None:
        """First pass: search-matched call (strongest signal). Second pass:
        any call matching ``data_kind`` — the agent gets back a full event
        list either way, so discovery still happened.

        Handles both argument shapes MCP accepts:
          - flat: ``{"kind": "events", "search": "pageview"}``
          - nested: ``{"query": {"kind": "events", "search": "pageview"}}``
        """
        search_terms = list(search_any_of)

        def _extract(tool_input: dict[str, Any]) -> tuple[str | None, str]:
            inner = tool_input.get("query") if isinstance(tool_input.get("query"), dict) else tool_input
            kind = inner.get("kind") if isinstance(inner, dict) else None
            raw_search = inner.get("search", "") if isinstance(inner, dict) else ""
            search = raw_search.lower() if isinstance(raw_search, str) else ""
            return (kind if isinstance(kind, str) else None, search)

        # Pass 1: prefer the call whose search matches a target term.
        if search_terms:
            for call in ordered:
                if call.name != READ_DATA_SCHEMA_TOOL_NAME:
                    continue
                kind, search_val = _extract(call.input)
                if data_kind and kind != data_kind:
                    continue
                if any(term in search_val for term in search_terms):
                    return call.position

        # Pass 2: any successful call with the right kind — the response is
        # the full event list, which still lets the agent verify.
        for call in ordered:
            if call.name != READ_DATA_SCHEMA_TOOL_NAME:
                continue
            kind, _ = _extract(call.input)
            if data_kind and kind != data_kind:
                continue
            return call.position
        return None

    @staticmethod
    def _find_query_tool_pos(ordered: list[ToolCall], query_tool: str) -> int | None:
        for call in ordered:
            if call.name == query_tool:
                return call.position
        return None
