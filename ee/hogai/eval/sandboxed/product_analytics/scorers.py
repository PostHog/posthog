"""Product-analytics scorers for the sandboxed agent evals.

Retention scorers extract the final ``query-retention`` MCP tool call and
grade it against an expected shape or against the user prompt. Binary
outputs only — the LLM is asked yes/no.

``SchemaDiscoveryOrder`` is a deterministic scorer that asserts the agent
first loads the target MCP tool schema (via Claude Code's ``ToolSearch``
deferred-tool loader, which is what the MCP CLI's ``info <tool>`` maps to
in the sandbox), then verifies the data schema via ``read-data-schema``,
and only then runs the actual query tool.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from autoevals.llm import LLMClassifier
from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.scorers import iter_successful_tool_calls, normalize_tool_name

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

QUERY_RETENTION_TOOL_NAME = "query-retention"
READ_DATA_SCHEMA_TOOL_NAME = "read-data-schema"
TOOL_SEARCH_TOOL_NAME = "ToolSearch"
EXEC_TOOL_NAME = "exec"
# Synthetic prefix assigned to `mcp__posthog__exec {command: "info <tool>"}` so
# the scorer can treat the exec-wrapped ``info`` command and the per-tool
# ``ToolSearch(select:mcp__posthog__<tool>)`` as interchangeable "tool schema
# loaded" signals.
_INFO_SYNTHETIC_PREFIX = "__info__:"

BINARY_CHOICE_SCORES = {"yes": 1.0, "no": 0.0}

_JUDGE_MODEL = "gpt-4.1"


def extract_last_query_retention_input(output: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the input dict of the most recent successful ``query-retention`` call.

    Returns ``None`` when the agent never ran the tool successfully — scorers
    that depend on this should short-circuit with ``score=None`` in that case
    rather than counting it as an incorrect retention query.
    """
    if not output:
        return None
    messages = output.get("messages")
    if not messages:
        return None

    last_input: dict[str, Any] | None = None
    for tool_use, _ in iter_successful_tool_calls(messages):
        if normalize_tool_name(tool_use.get("name")) != QUERY_RETENTION_TOOL_NAME:
            continue
        tool_input = tool_use.get("input")
        if isinstance(tool_input, dict):
            last_input = tool_input
    return last_input


class RetentionSchemaAlignment(LLMClassifier):
    """Binary yes/no: does the retention query the agent ran match the expected one?"""

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return await self._judge_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._judge_sync(output, expected, **kwargs)

    async def _judge_async(self, output, expected, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        return await super()._run_eval_async(prepared["output"], prepared["expected"], **kwargs)

    def _judge_sync(self, output, expected, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        return super()._run_eval_sync(prepared["output"], prepared["expected"], **kwargs)

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        actual = extract_last_query_retention_input(output)
        if actual is None:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "Agent never ran query-retention successfully"},
            )
        expected_query = (expected or {}).get("retention_query") if isinstance(expected, dict) else None
        if not isinstance(expected_query, dict):
            return Score(
                name=self._name(),
                score=None,
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
            max_tokens=512,
            **kwargs,
        )


class RetentionTimeRangeRelevancy(LLMClassifier):
    """Binary yes/no: is the retention query's time range / period consistent with the user prompt?"""

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return await self._judge_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._judge_sync(output, expected, **kwargs)

    async def _judge_async(self, output, expected, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        return await super()._run_eval_async(prepared["output"], prepared["expected"], **kwargs)

    def _judge_sync(self, output, expected, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        return super()._run_eval_sync(prepared["output"], prepared["expected"], **kwargs)

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        actual = extract_last_query_retention_input(output)
        if actual is None:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "Agent never ran query-retention successfully"},
            )
        prompt = _extract_user_prompt(output)
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
            max_tokens=512,
            **kwargs,
        )


def _extract_user_prompt(output: dict[str, Any] | None) -> str:
    """Fish the original user prompt out of the sandbox task output.

    The eval harness doesn't surface the prompt on the task return dict, but
    ``parse_log(..., initial_prompt=eval_case.prompt)`` seeds it as the first
    user message, so reading ``messages[0]`` is reliable. Keeps the scorer
    decoupled from how ``base.py`` chooses to expose the prompt.
    """
    if not isinstance(output, dict):
        return ""
    for key in ("prompt", "input"):
        value = output.get(key)
        if isinstance(value, str) and value:
            return value
    messages = output.get("messages") or []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
            # First user message may be tool_results in a multi-turn thread —
            # in that case keep scanning.
    return ""


def _parse_exec_command(command: str) -> tuple[str, dict[str, Any]] | None:
    """Split a CLI-style ``exec`` command string into ``(virtual_name, input)``.

    Recognized shapes (produced by single-exec mode where the agent talks to
    the PostHog MCP through one ``exec`` tool):
      - ``"info <tool>"``          → ``("__info__:<tool>", {})``
      - ``"call [--json] <tool> <json>"`` → ``("<tool>", parsed_json)``

    Anything else (``search``, ``tools``, ``schema``, malformed) returns
    ``None`` so the caller can fall back to emitting the raw ``exec`` call —
    those commands aren't load-bearing for the ordering checks.
    """
    stripped = command.strip()
    if not stripped:
        return None

    head, _, rest = stripped.partition(" ")
    head = head.lower()

    if head == "info":
        tool = rest.strip().split(None, 1)[0] if rest.strip() else ""
        if tool:
            return (f"{_INFO_SYNTHETIC_PREFIX}{tool}", {})
        return None

    if head == "call":
        rest = rest.strip()
        # Optional --json flag
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


def _enumerate_tool_calls(messages: list[dict[str, Any]]) -> list[tuple[int, str, dict[str, Any]]]:
    """Return a chronological list of ``(position, normalized_name, tool_use)``.

    Position is the index of the enclosing assistant message inside the flat
    ``messages`` list, which preserves the execution order the ACP log emits
    (``base.py`` rebuilds the conversation history in order, so message index
    ≈ time). Includes only successful calls — error results are skipped the
    same way ``iter_successful_tool_calls`` does.

    Also unwraps ``mcp__posthog__exec`` calls from single-exec mode: each
    ``call <tool> <json>`` becomes a synthetic ``(pos, <tool>, parsed_input)``
    entry, and each ``info <tool>`` becomes ``(pos, "__info__:<tool>", {})``.
    This way ordering checks don't care whether the agent talks to tools
    directly or through the CLI wrapper.
    """
    positions: dict[str, int] = {}
    for idx, msg in enumerate(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                call_id = block.get("id")
                if call_id and call_id not in positions:
                    positions[call_id] = idx

    ordered: list[tuple[int, str, dict[str, Any]]] = []
    for tool_use, _result in iter_successful_tool_calls(messages):
        call_id = tool_use.get("id", "")
        name = normalize_tool_name(tool_use.get("name"))
        pos = positions.get(call_id, -1)
        # Unwrap single-exec CLI commands so downstream checks see the inner tool.
        if name == EXEC_TOOL_NAME:
            tool_input = tool_use.get("input") or {}
            command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
            parsed = _parse_exec_command(command)
            if parsed is not None:
                virtual_name, virtual_input = parsed
                synthetic_use = {
                    "id": tool_use.get("id"),
                    "name": virtual_name,
                    "input": virtual_input,
                }
                ordered.append((pos, virtual_name, synthetic_use))
                continue
        ordered.append((pos, name, tool_use))
    ordered.sort(key=lambda item: item[0])
    return ordered


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
        messages = output.get("messages")
        if not messages:
            return Score(name=self._name(), score=None, metadata={"reason": "No parsed messages"})

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

        ordered = _enumerate_tool_calls(messages)

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
    def _find_tool_search_pos(ordered: list[tuple[int, str, dict[str, Any]]], query_tool: str) -> int | None:
        """Match either Claude-Code's ``ToolSearch`` (per-tool MCP mode) or
        the synthetic ``__info__:<tool>`` entry emitted by single-exec's
        ``info <tool>`` command — both represent "tool schema loaded"."""
        needle = query_tool.lower()
        info_synthetic = f"{_INFO_SYNTHETIC_PREFIX}{query_tool}".lower()
        for pos, name, tool_use in ordered:
            if name.lower() == info_synthetic:
                return pos
            if name != TOOL_SEARCH_TOOL_NAME:
                continue
            query = ""
            tool_input = tool_use.get("input")
            if isinstance(tool_input, dict):
                raw = tool_input.get("query", "")
                query = raw.lower() if isinstance(raw, str) else ""
            if needle in query:
                return pos
        return None

    @staticmethod
    def _find_read_data_schema_pos(
        ordered: list[tuple[int, str, dict[str, Any]]],
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
            for pos, name, tool_use in ordered:
                if name != READ_DATA_SCHEMA_TOOL_NAME:
                    continue
                tool_input = tool_use.get("input")
                if not isinstance(tool_input, dict):
                    continue
                kind, search_val = _extract(tool_input)
                if data_kind and kind != data_kind:
                    continue
                if any(term in search_val for term in search_terms):
                    return pos

        # Pass 2: any successful call with the right kind — the response is
        # the full event list, which still lets the agent verify.
        for pos, name, tool_use in ordered:
            if name != READ_DATA_SCHEMA_TOOL_NAME:
                continue
            tool_input = tool_use.get("input")
            if not isinstance(tool_input, dict):
                continue
            kind, _ = _extract(tool_input)
            if data_kind and kind != data_kind:
                continue
            return pos
        return None

    @staticmethod
    def _find_query_tool_pos(ordered: list[tuple[int, str, dict[str, Any]]], query_tool: str) -> int | None:
        for pos, name, _tool_use in ordered:
            if name == query_tool:
                return pos
        return None
