"""Retention scorers for the sandboxed product-analytics eval.

Both scorers extract the final ``query-retention`` MCP tool call the agent
made, then grade it against an expected shape or against the user prompt.
Binary outputs only — the LLM is asked yes/no.
"""

from __future__ import annotations

from typing import Any

from autoevals.llm import LLMClassifier
from braintrust import Score

from ee.hogai.eval.sandboxed.scorers import iter_successful_tool_calls, normalize_tool_name

QUERY_RETENTION_TOOL_NAME = "query-retention"

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
