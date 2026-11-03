from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.ai_observability.backend.models.evaluation_outcomes import (
    CATEGORIES_EXPRESSION,
    CATEGORIZED_PREDICATE,
    NOT_SKIPPED_PREDICATE,
    NUMERIC_SCORED_PREDICATE,
    SCORE_EXPRESSION,
    SENTIMENT_LABELS,
    get_outcome_definition,
)

from .pass_filters import PassRules
from .period import OverviewPeriod, PeriodBounds

_SKIPPED = "properties.$ai_evaluation_skipped = 'true'"
_NOT_APPLICABLE = f"properties.$ai_evaluation_applicable = 'false' AND {NOT_SKIPPED_PREDICATE}"
_SENTIMENT = get_outcome_definition("sentiment")
# One column per label, in the order of SENTIMENT_LABELS, which `load_bucket_counts` reads them in.
_SENTIMENT_COUNTS = ", ".join(
    f"countIf({_SENTIMENT.outcome_predicates[label]} AND {NOT_SKIPPED_PREDICATE}) AS {label}"
    for label in SENTIMENT_LABELS
)
_ANY_LABEL = ", ".join(f"'{label}'" for label in SENTIMENT_LABELS)

# A run that a summary kind without a passing rule grades: scored, categorized or labeled.
GRADED_WITHOUT_RULE = (
    f"({NUMERIC_SCORED_PREDICATE}) OR ({CATEGORIZED_PREDICATE})"
    f" OR ({_SENTIMENT.result_expression} IN ({_ANY_LABEL}) AND {NOT_SKIPPED_PREDICATE})"
)
# A run any summary kind grades, so an evaluation whose recent runs were all N/A or skipped still reads as silent
# since its last real result.
_GRADED_ANY = f"graded_run OR {GRADED_WITHOUT_RULE}"

PAGE_SIZE = MAX_SELECT_RETURNED_ROWS
# Many evaluations over a long period can group into more rows than one response returns, for example categorical
# evaluations with many categories over 90 days. So a read splits the evaluations into batches that are expected to
# fit in half a page, and splits a batch again if it still fills a page.
BATCH_ROWS = PAGE_SIZE // 2
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
    countIf(and(({{graded}}) AS graded_run, ({{passes}}) AS passing_run)) AS passed,
    countIf(graded_run AND NOT passing_run) AS failed,
    countIf({_NOT_APPLICABLE}) AS not_applicable,
    countIf({_SKIPPED}) AS skipped,
    countIf({NUMERIC_SCORED_PREDICATE}) AS score_count,
    sumIf({SCORE_EXPRESSION}, {NUMERIC_SCORED_PREDICATE}) AS score_sum,
    countIf({CATEGORIZED_PREDICATE}) AS categorized,
    {_SENTIMENT_COUNTS},
    if(countIf(({_GRADED_ANY}) AS graded_any) = 0, NULL, maxIf(timestamp, graded_any)) AS last_run_at
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
    arrayJoin(if(empty({CATEGORIES_EXPRESSION}), [''], {CATEGORIES_EXPRESSION})) AS category,
    count() AS runs
FROM events
WHERE {_WHERE} AND {CATEGORIZED_PREDICATE}
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
    expected_rows: Mapping[str, int],
    extra: dict[str, ast.Expr],
) -> list[Sequence[Any]]:
    """`expected_rows` maps each evaluation to read to the most rows it is expected to group into."""
    placeholders: dict[str, ast.Expr] = {
        "previous_start": instant(period.previous_start),
        "previous_end": instant(period.previous_end),
        "current_start": instant(period.start),
        "end": instant(period.end),
        "bucket_start": _bucket_start(period, team.timezone),
        **extra,
    }

    def read(evaluation_ids: Sequence[str], offset: int) -> list[Sequence[Any]]:
        # One placeholder for the whole list, so the query text stays the same size however many evaluations it reads.
        ids = ast.Constant(value=tuple(evaluation_ids))
        limits = {"limit": ast.Constant(value=PAGE_SIZE), "offset": ast.Constant(value=offset)}
        return run_evaluation_query(name, query, team, user, {**placeholders, "evaluation_ids": ids, **limits})

    def read_all(evaluation_ids: Sequence[str]) -> list[Sequence[Any]]:
        rows = read(evaluation_ids, 0)
        if len(rows) < PAGE_SIZE:
            return rows
        if len(evaluation_ids) > 1:
            middle = len(evaluation_ids) // 2
            return read_all(evaluation_ids[:middle]) + read_all(evaluation_ids[middle:])
        # One evaluation cannot be split further, so it pages through its own rows.
        while len(page := read(evaluation_ids, len(rows))) == PAGE_SIZE:
            rows += page
        return rows + page

    return [row for batch in _batches(expected_rows) for row in read_all(batch)]


def _bucket_start(period: OverviewPeriod, timezone: str) -> ast.Expr:
    timestamp = ast.Field(chain=["timestamp"])
    if period.interval == "hour":
        # Whole hours from the first bucket, the way `overview_period` steps its buckets. Local hours would split a
        # bucket where a daylight saving change moves the clocks by half an hour. ClickHouse needs an origin before
        # every timestamp, including the previous period's, so the origin is the first bucket's minute in 1970. It
        # counts in the timestamp's timezone, which is UTC so that past offset changes do not shift the hours.
        first = (period.buckets[0] if period.buckets else period.start).astimezone(UTC)
        origin = instant(datetime(1970, 1, 1, minute=first.minute, tzinfo=UTC))
        utc = ast.Call(name="toTimeZone", args=[timestamp, ast.Constant(value="UTC")])
        return ast.Call(
            name="toStartOfInterval",
            args=[utc, ast.Call(name="toIntervalHour", args=[ast.Constant(value=1)]), origin],
        )
    # The project's timezone is explicit, because the team's modifiers can turn off the conversion to it, and
    # `overview_period` builds its buckets in that timezone.
    local = ast.Call(name="toTimeZone", args=[timestamp, ast.Constant(value=timezone)])
    return ast.Call(name="toStartOfDay", args=[local])


def _groups(period: OverviewPeriod) -> int:
    """The most rows one evaluation groups into per category: one per bucket, plus one for the previous period."""
    return len(period.buckets) + 1


def _batches(expected_rows: Mapping[str, int]) -> Iterator[list[str]]:
    batch: list[str] = []
    rows = 0
    for evaluation_id, expected in expected_rows.items():
        if batch and rows + expected > BATCH_ROWS:
            yield batch
            batch, rows = [], 0
        batch.append(evaluation_id)
        rows += expected
    if batch:
        yield batch


def instant(value: datetime) -> ast.Expr:
    """A datetime constant prints as wall time in the project's timezone, which names two instants in a repeated
    daylight saving hour. UTC wall time names exactly one."""
    return ast.Call(
        name="toDateTime64",
        args=[
            ast.Constant(value=value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")),
            ast.Constant(value=6),
            ast.Constant(value="UTC"),
        ],
    )


# The runs of one evaluation in a period, for the reads that list or bucket them.
EVALUATION_RUNS_WHERE = (
    "event = '$ai_evaluation' AND properties.$ai_evaluation_id = {evaluation_id}"
    " AND timestamp >= {start} AND timestamp < {end}"
)


def evaluation_runs_placeholders(evaluation_id: str, period: PeriodBounds) -> dict[str, ast.Expr]:
    return {
        "evaluation_id": ast.Constant(value=evaluation_id),
        "start": instant(period.start),
        "end": instant(period.end),
    }


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
    pass_rules: PassRules,
) -> list[EvaluationBucketCounts]:
    if not evaluation_ids:
        return []
    rows = _run(
        "ai_evaluations_overview_counts",
        _COUNTS_QUERY,
        team,
        user,
        period,
        dict.fromkeys(evaluation_ids, _groups(period)),
        {"graded": pass_rules.graded, "passes": pass_rules.passes},
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
    team: Team, user: User | None, period: OverviewPeriod, configured_categories: Mapping[str, int]
) -> list[CategoryBucketCount]:
    """`configured_categories` maps each evaluation to read to the number of categories its config lists."""
    if not configured_categories:
        return []
    # Runs can hold keys the config no longer lists, so the estimate doubles the configured keys and the '' row.
    expected_rows = {
        evaluation_id: _groups(period) * 2 * (configured + 1)
        for evaluation_id, configured in configured_categories.items()
    }
    rows = _run("ai_evaluations_overview_categories", _CATEGORY_QUERY, team, user, period, expected_rows, {})
    return [CategoryBucketCount(evaluation_id=row[0], bucket=row[1], key=row[2], runs=row[3]) for row in rows]
