"""Plain-text score table for `run_support_reply_eval`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from posthog.dataclasses import frozen

from products.conversations.evals.fixtures import SupportReplyFixture
from products.posthog_ai.eval_harness.scorers.contract import Score


@frozen
class EvalRow:
    fixture: SupportReplyFixture
    output: dict[str, Any]
    scores: dict[str, Score]


def _cell(score: Score | None) -> str:
    if score is None or score.score is None:
        return "-"
    return f"{score.score:.2f}"


def format_report(rows: Sequence[EvalRow]) -> str:
    header = (
        f"{'fixture':<34} {'expected':<22} {'actual':<22} "
        f"{'outcome':<8} {'cite':<6} {'forbid':<7} {'cost':<6} {'s':>7} {'llm':>4}"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        fixture, output, scores = row.fixture, row.output, row.scores
        raw_cost = output.get("cost")
        cost = raw_cost if isinstance(raw_cost, dict) else {}
        sandbox = cost.get("sandbox_seconds")
        llm_calls = cost.get("llm_calls")
        sandbox_cell = f"{sandbox:.1f}" if isinstance(sandbox, (int, float)) else "-"
        llm_cell = str(llm_calls) if isinstance(llm_calls, int) else "-"
        error = output.get("error")
        actual = error if error else (output.get("eval_outcome") or "-")
        lines.append(
            f"{fixture.name:<34} {fixture.expected_outcome:<22} {str(actual)[:22]:<22} "
            f"{_cell(scores.get('outcome_match')):<8} "
            f"{_cell(scores.get('citation_precision')):<6} "
            f"{_cell(scores.get('forbidden_claims')):<7} "
            f"{_cell(scores.get('cost')):<6} "
            f"{sandbox_cell:>7} {llm_cell:>4}"
        )
    return "\n".join(lines)
