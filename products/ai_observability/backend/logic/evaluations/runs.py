from typing import Literal

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import clone_expr

from posthog.models import Team, User

from ...facade import contracts
from .overview_queries import (
    EVALUATION_RUNS_WHERE,
    GRADED_WITHOUT_RULE,
    evaluation_runs_placeholders,
    run_evaluation_query,
)
from .pass_filters import PassRules
from .period import PeriodBounds

RunOutcome = Literal["passed", "failed"]

REASONING_MAX_CHARS = 1000

_RUNS_QUERY = f"""
SELECT
    timestamp,
    if({{graded}}, if({{passes}}, 'passed', 'failed'), NULL),
    properties.$ai_evaluation_reasoning,
    properties.$ai_target_event_id,
    properties.$ai_trace_id
FROM events
WHERE {EVALUATION_RUNS_WHERE} AND {{matches}}
ORDER BY timestamp DESC
LIMIT {{limit}}
"""


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _truncate(value: object) -> str | None:
    text = _text(value)
    if text is None or len(text) <= REASONING_MAX_CHARS:
        return text
    return f"{text[: REASONING_MAX_CHARS - 1]}…"


def _matches(pass_rules: PassRules, outcome: RunOutcome | None) -> ast.Expr:
    # Copies, because the select reads the same rule expressions.
    graded, passes = clone_expr(pass_rules.graded), clone_expr(pass_rules.passes)
    if outcome == "passed":
        return ast.And(exprs=[graded, passes])
    if outcome == "failed":
        return ast.And(exprs=[graded, ast.Not(expr=passes)])
    return ast.Or(exprs=[graded, parse_expr(GRADED_WITHOUT_RULE)])


def load_runs(
    team: Team,
    user: User | None,
    evaluation_id: str,
    period: PeriodBounds,
    pass_rules: PassRules,
    outcome: RunOutcome | None,
    limit: int,
) -> list[contracts.EvaluationRun]:
    rows = run_evaluation_query(
        "ai_evaluations_runs",
        _RUNS_QUERY,
        team,
        user,
        {
            **evaluation_runs_placeholders(evaluation_id, period),
            "graded": pass_rules.graded,
            "passes": pass_rules.passes,
            "matches": _matches(pass_rules, outcome),
            "limit": ast.Constant(value=limit),
        },
    )
    return [
        contracts.EvaluationRun(
            timestamp=row[0],
            outcome=row[1],
            reasoning=_truncate(row[2]),
            target_event_id=_text(row[3]),
            trace_id=_text(row[4]),
        )
        for row in rows
    ]
