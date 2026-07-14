"""Scorers for the one-shot MCP benchmark port.

They read the output dict produced by ``eval_mcp_sql``'s task function:
``{"prompt", "query", "results", "columns", "error", ...}``.
"""

from __future__ import annotations

import json
from typing import Any

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer

_MAX_RESULT_CHARS_FOR_JUDGE = 8_000


class QueryExecutes(Scorer):
    """Binary: the generation produced a HogQL query that executed and returned rows."""

    def _name(self) -> str:
        return "query_executes"

    def _run_eval_sync(self, output: dict[str, Any] | None, expected: Any = None, **kwargs: Any) -> Score:
        if not isinstance(output, dict):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        if not output.get("query"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "Model produced no SQL query"})
        error = output.get("error")
        if error:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"Query failed: {str(error)[:300]}"})
        results = output.get("results") or []
        if not results:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Query returned no rows"})
        return Score(name=self._name(), score=1.0, metadata={"rows": len(results)})


SUCCESS_CRITERIA_PROMPT = """
You are judging whether a one-shot SQL generation against a PostHog project satisfied a benchmark task's success criteria.

The model was given a natural-language analytics request and produced a single HogQL query, which was then executed against a seeded demo project with ~120 days of event data.

Task intent:
<intent>
{{output.prompt}}
</intent>

Executed HogQL query:
<query>
{{output.query}}
</query>

Result columns: {{output.columns}}

Result rows (possibly truncated):
<results>
{{output.results}}
</results>

Success criteria:
<criteria>
{{expected.criteria}}
</criteria>

Judge only whether the executed query and its actual result satisfy the success criteria for the stated intent. A plausible-looking query whose result does not actually match the criteria (wrong grouping, wrong time window, empty or irrelevant rows) is a "no".

Answer "yes" or "no".
""".strip()


class SuccessCriteria(JudgedScorer):
    """Binary judge: does the executed query's result satisfy the benchmark task's success criteria?"""

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        if not isinstance(output, dict) or not output.get("query"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "Model produced no SQL query"})
        if output.get("error"):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": f"Query failed: {str(output['error'])[:300]}"},
            )
        criteria = (expected or {}).get("success_criteria") if isinstance(expected, dict) else None
        if not isinstance(criteria, str) or not criteria.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No expected.success_criteria provided"})
        results_rendered = json.dumps(output.get("results") or [], default=str)
        if len(results_rendered) > _MAX_RESULT_CHARS_FOR_JUDGE:
            results_rendered = f"{results_rendered[:_MAX_RESULT_CHARS_FOR_JUDGE]}\n...[truncated for judge]..."
        return {
            "output": {
                "prompt": output.get("prompt", ""),
                "query": output["query"],
                "columns": json.dumps(output.get("columns") or [], default=str),
                "results": results_rendered,
            },
            "expected": {"criteria": criteria},
        }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="success_criteria",
            prompt_template=SUCCESS_CRITERIA_PROMPT,
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )
