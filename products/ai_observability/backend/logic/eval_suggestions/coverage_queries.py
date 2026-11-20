from collections.abc import Sequence
from datetime import datetime

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.ai_observability.backend.models.evaluation_outcomes import APPLICABLE_PREDICATE, NOT_SKIPPED_PREDICATE

from .queries import run_query

_EVAL_RUNS_SQL = (
    """
SELECT
    toString(properties.$ai_evaluation_id) AS evaluation_id,
    count() AS runs,
    countIf(toString(properties.$ai_evaluation_result) = 'true') AS true_runs,
    countIf(toString(properties.$ai_evaluation_result) = 'false') AS false_runs
FROM events
WHERE event = '$ai_evaluation'
  AND timestamp >= {start}
  AND toString(properties.$ai_evaluation_id) IN {evaluation_ids}
  AND """
    + NOT_SKIPPED_PREDICATE
    + " AND "
    + APPLICABLE_PREDICATE
    + """
GROUP BY evaluation_id
LIMIT 10000
"""
)

# Runs whose reasoning text, word for word, also explains the opposite outcome somewhere else.
_SHARED_REASONING_SQL = """
SELECT evaluation_id, sum(true_runs + false_runs) AS shared_runs
FROM (
    SELECT
        toString(properties.$ai_evaluation_id) AS evaluation_id,
        cityHash64(toString(properties.$ai_evaluation_reasoning)) AS reasoning,
        countIf(toString(properties.$ai_evaluation_result) = 'true') AS true_runs,
        countIf(toString(properties.$ai_evaluation_result) = 'false') AS false_runs
    FROM events
    WHERE event = '$ai_evaluation'
      AND timestamp >= {start}
      AND toString(properties.$ai_evaluation_id) IN {evaluation_ids}
      AND length(toString(properties.$ai_evaluation_reasoning)) > 20
    GROUP BY evaluation_id, reasoning
)
WHERE true_runs > 0 AND false_runs > 0
GROUP BY evaluation_id
LIMIT 10000
"""

_MATCHING_GENERATIONS_SQL = """
SELECT count()
FROM events
WHERE event = '$ai_generation' AND timestamp >= {start} AND timestamp < {end} AND {condition}
"""

_PROPERTY_VALUES_SQL = """
SELECT toString({property}) AS value, count() AS generations
FROM events
WHERE event = '$ai_generation' AND timestamp >= {start} AND timestamp < {end} AND notEmpty(toString({property}))
GROUP BY value
ORDER BY generations DESC
LIMIT 50
"""


@frozen
class EvaluationRunCounts:
    """Graded runs of one evaluation: skipped and not-applicable runs are left out."""

    evaluation_id: str
    runs: int
    true_runs: int
    false_runs: int


@frozen
class SharedReasoningRow:
    evaluation_id: str
    shared_runs: int


@frozen
class PropertyValueRow:
    value: str
    generations: int


def load_evaluation_runs(team: Team, evaluation_ids: Sequence[str], since: datetime) -> list[EvaluationRunCounts]:
    rows = run_query(
        team,
        _EVAL_RUNS_SQL,
        {"start": ast.Constant(value=since), "evaluation_ids": ast.Constant(value=list(evaluation_ids))},
        "EvalSuggestionsEvaluationRuns",
    )
    return [
        EvaluationRunCounts(evaluation_id=str(row[0]), runs=int(row[1]), true_runs=int(row[2]), false_runs=int(row[3]))
        for row in rows
    ]


def load_shared_reasoning(team: Team, evaluation_ids: Sequence[str], since: datetime) -> list[SharedReasoningRow]:
    rows = run_query(
        team,
        _SHARED_REASONING_SQL,
        {"start": ast.Constant(value=since), "evaluation_ids": ast.Constant(value=list(evaluation_ids))},
        "EvalSuggestionsSharedReasoning",
    )
    return [SharedReasoningRow(evaluation_id=str(row[0]), shared_runs=int(row[1])) for row in rows]


def count_matching_generations(team: Team, condition: ast.Expr, start: datetime, end: datetime) -> int:
    rows = run_query(
        team,
        _MATCHING_GENERATIONS_SQL,
        {"start": ast.Constant(value=start), "end": ast.Constant(value=end), "condition": condition},
        "EvalSuggestionsConditionMatches",
    )
    return int(rows[0][0]) if rows else 0


def load_property_values(team: Team, key: str, start: datetime, end: datetime) -> list[PropertyValueRow]:
    rows = run_query(
        team,
        _PROPERTY_VALUES_SQL,
        {
            "property": ast.Field(chain=["properties", key]),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
        },
        "EvalSuggestionsPropertyValues",
    )
    return [PropertyValueRow(value=str(row[0]), generations=int(row[1])) for row in rows]
