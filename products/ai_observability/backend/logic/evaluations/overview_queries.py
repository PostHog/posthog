from collections.abc import Sequence
from datetime import datetime
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.ai_observability.backend.models.evaluation_outcomes import (
    APPLICABLE_PREDICATE,
    NOT_SKIPPED_PREDICATE,
    get_outcome_definition,
)

from ...facade import contracts
from .period import Interval, OverviewPeriod

_SKIPPED = "properties.$ai_evaluation_skipped = 'true'"
_NOT_SKIPPED = NOT_SKIPPED_PREDICATE
_NOT_APPLICABLE = f"properties.$ai_evaluation_applicable = 'false' AND {_NOT_SKIPPED}"
# Same as EVALUATION_NUMERIC_GRADED_HOGQL and EVALUATION_CATEGORICAL_GRADED_HOGQL in the frontend's constants.ts.
NUMERIC_SCORED = (
    "properties.$ai_evaluation_result_type = 'numeric' AND properties.$ai_evaluation_numeric_result IS NOT NULL"
    f" AND {APPLICABLE_PREDICATE} AND {_NOT_SKIPPED}"
)
_CATEGORIZED = f"properties.$ai_evaluation_result_type = 'categorical' AND properties.$ai_evaluation_applicable = 'true' AND {_NOT_SKIPPED}"
_CATEGORIES = get_outcome_definition("categorical").result_expression
SCORE = "toFloat(properties.$ai_evaluation_numeric_result)"

# A run any summary kind grades, so an evaluation whose recent runs were all N/A or skipped still reads as silent
# since its last real result.
_GRADED_ANY = (
    f"({{graded}}) OR ({NUMERIC_SCORED}) OR ({_CATEGORIZED})"
    f" OR (properties.$ai_sentiment_label IN ('positive', 'neutral', 'negative') AND {_NOT_SKIPPED})"
)

_BUCKET_FUNCTIONS: dict[Interval, str] = {"hour": "toStartOfHour", "day": "toStartOfDay"}
# Many evaluations over a long period can group into more rows than one response returns, for example categorical
# evaluations with many categories over 90 days, so a read pages until a page comes back short.
PAGE_SIZE = MAX_SELECT_RETURNED_ROWS
# A null bucket marks the previous period, which needs totals only, so it costs one row per evaluation.
_BUCKET = "if(timestamp < {current_start}, NULL, {bucket_start})"
_WHERE = (
    "event = '$ai_evaluation' AND timestamp >= {previous_start} AND timestamp < {end}"
    " AND (timestamp >= {current_start} OR timestamp < {previous_end})"
    " AND properties.$ai_evaluation_id IN {evaluation_ids}"
)

_COUNTS_QUERY = f"""
SELECT
    toString(properties.$ai_evaluation_id) AS evaluation_id,
    {_BUCKET} AS bucket,
    countIf({{passed}}) AS passed,
    countIf({{graded}} AND NOT {{passed}}) AS failed,
    countIf({_NOT_APPLICABLE}) AS not_applicable,
    countIf({_SKIPPED}) AS skipped,
    countIf({NUMERIC_SCORED}) AS score_count,
    sumIf({SCORE}, {NUMERIC_SCORED}) AS score_sum,
    countIf({_CATEGORIZED}) AS categorized,
    countIf(properties.$ai_sentiment_label = 'positive' AND {_NOT_SKIPPED}) AS positive,
    countIf(properties.$ai_sentiment_label = 'neutral' AND {_NOT_SKIPPED}) AS neutral,
    countIf(properties.$ai_sentiment_label = 'negative' AND {_NOT_SKIPPED}) AS negative,
    if(countIf({_GRADED_ANY}) = 0, NULL, maxIf(timestamp, {_GRADED_ANY})) AS last_run_at
FROM events
WHERE {_WHERE}
GROUP BY evaluation_id, bucket
ORDER BY evaluation_id, bucket
LIMIT {{limit}} OFFSET {{offset}}
"""

# An empty category list becomes one '' row, so multiple-selection runs that chose nothing are counted too.
_CATEGORY_QUERY = f"""
SELECT
    toString(properties.$ai_evaluation_id) AS evaluation_id,
    {_BUCKET} AS bucket,
    arrayJoin(if(empty({_CATEGORIES}), [''], {_CATEGORIES})) AS category,
    count() AS runs
FROM events
WHERE {_WHERE} AND {_CATEGORIZED}
GROUP BY evaluation_id, bucket, category
ORDER BY evaluation_id, bucket, category
LIMIT {{limit}} OFFSET {{offset}}
"""


@frozen
class EvaluationBucketCounts:
    evaluation_id: str
    bucket: datetime | None  # None is the previous period.
    passed: int
    failed: int
    not_applicable: int
    skipped: int
    score_count: int
    score_sum: float
    categorized: int
    positive: int
    neutral: int
    negative: int
    last_run_at: datetime | None


@frozen
class CategoryBucketCount:
    evaluation_id: str
    bucket: datetime | None  # None is the previous period.
    key: str  # '' for a run that chose no category.
    runs: int


def _run(
    name: str,
    query: str,
    team: Team,
    user: User | None,
    period: OverviewPeriod,
    evaluation_ids: Sequence[str],
    extra: dict[str, ast.Expr],
) -> list[Sequence[Any]]:
    placeholders: dict[str, ast.Expr] = {
        "previous_start": ast.Constant(value=period.previous_start),
        "previous_end": ast.Constant(value=period.previous_end),
        "current_start": ast.Constant(value=period.start),
        "end": ast.Constant(value=period.end),
        # The project's timezone is explicit, because the team's modifiers can turn off the conversion to it, and
        # `overview_period` builds its buckets in that timezone.
        "bucket_start": ast.Call(
            name=_BUCKET_FUNCTIONS[period.interval],
            args=[
                ast.Call(name="toTimeZone", args=[ast.Field(chain=["timestamp"]), ast.Constant(value=team.timezone)])
            ],
        ),
        "evaluation_ids": ast.Tuple(exprs=[ast.Constant(value=value) for value in evaluation_ids]),
        **extra,
    }
    rows: list[Sequence[Any]] = []
    while True:
        page = run_evaluation_query(
            name,
            query,
            team,
            user,
            {**placeholders, "limit": ast.Constant(value=PAGE_SIZE), "offset": ast.Constant(value=len(rows))},
        )
        rows += page
        if len(page) < PAGE_SIZE:
            return rows


def run_evaluation_query(
    name: str, query: str, team: Team, user: User | None, placeholders: dict[str, ast.Expr]
) -> list[Sequence[Any]]:
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=name)
        response = execute_hogql_query(
            query=parse_select(query, placeholders=placeholders),
            team=team,
            user=user,
            query_type=name,
            context=HogQLContext(
                team_id=team.pk, team=team, user=user, database=Database.create_for_posthog_tables(team)
            ),
        )
    return list(response.results or [])


def load_bucket_counts(
    team: Team,
    user: User | None,
    period: OverviewPeriod,
    evaluation_ids: Sequence[str],
    pass_filters: contracts.EvaluationPassFilters,
) -> list[EvaluationBucketCounts]:
    if not evaluation_ids:
        return []
    rows = _run(
        "ai_evaluations_overview_counts",
        _COUNTS_QUERY,
        team,
        user,
        period,
        evaluation_ids,
        {"graded": parse_expr(pass_filters.graded), "passed": parse_expr(pass_filters.passed)},
    )
    return [
        EvaluationBucketCounts(
            evaluation_id=row[0],
            bucket=row[1],
            passed=row[2],
            failed=row[3],
            not_applicable=row[4],
            skipped=row[5],
            score_count=row[6],
            score_sum=float(row[7] or 0),
            categorized=row[8],
            positive=row[9],
            neutral=row[10],
            negative=row[11],
            last_run_at=row[12],
        )
        for row in rows
    ]


def load_category_counts(
    team: Team, user: User | None, period: OverviewPeriod, evaluation_ids: Sequence[str]
) -> list[CategoryBucketCount]:
    if not evaluation_ids:
        return []
    rows = _run("ai_evaluations_overview_categories", _CATEGORY_QUERY, team, user, period, evaluation_ids, {})
    return [CategoryBucketCount(evaluation_id=row[0], bucket=row[1], key=row[2], runs=row[3]) for row in rows]
