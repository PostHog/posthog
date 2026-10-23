"""Per-evaluation results for the online evaluations overview, and the totals across them.

Pure functions over the grouped counts from `overview_queries`.
"""

import math
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Literal, TypeVar

from posthog.dataclasses import frozen

from ...facade import contracts
from .overview_queries import CategoryBucketCount, EvaluationBucketCounts

# Below this many graded results a summary is shown greyed, and its change is not compared. A previous period with
# fewer is not compared either.
LOW_EVIDENCE_GRADED_COUNT = 30
# A change smaller than this, in percentage points, is not called out.
NOTABLE_CHANGE_PP = 2
# A bucket this many points worse than an evaluation's previous period counts as unusual.
DIP_PP = 3
# A numeric score counts as unusual when it moves this share of its scale away from its usual value.
SCORE_SHIFT_SHARE = 0.05

SummaryKind = Literal["pass_rate", "score", "categories", "sentiment"]

_Row = TypeVar("_Row", EvaluationBucketCounts, CategoryBucketCount)


def group_by_evaluation(rows: Iterable[_Row]) -> dict[str, list[_Row]]:
    grouped: dict[str, list[_Row]] = defaultdict(list)
    for row in rows:
        grouped[row.evaluation_id].append(row)
    return grouped


@frozen
class CategoryOption:
    key: str
    label: str


@frozen
class EvaluationMeta:
    id: str
    name: str
    directory_name: str | None
    evaluation_type: str
    output_type: str
    enabled: bool
    errored: bool
    status_reason: str | None
    created_by: str | None
    kind: SummaryKind
    scale: contracts.ScoreScale | None
    score_step: float | None
    categories: tuple[CategoryOption, ...]
    multiple: bool


@frozen
class _Totals:
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


def _sum(rows: Sequence[EvaluationBucketCounts]) -> _Totals:
    return _Totals(
        passed=sum(row.passed for row in rows),
        failed=sum(row.failed for row in rows),
        not_applicable=sum(row.not_applicable for row in rows),
        skipped=sum(row.skipped for row in rows),
        score_count=sum(row.score_count for row in rows),
        score_sum=sum(row.score_sum for row in rows),
        categorized=sum(row.categorized for row in rows),
        positive=sum(row.positive for row in rows),
        neutral=sum(row.neutral for row in rows),
        negative=sum(row.negative for row in rows),
    )


def _js_round(value: float, digits: int) -> float:
    # Math.round rounds halves up, where Python's round() rounds them to even.
    factor = 10**digits
    return math.floor(value * factor + 0.5) / factor


def _share(part: float, whole: float) -> float:
    return part / whole * 100 if whole > 0 else 0


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def pass_rate(passed: int, failed: int) -> float | None:
    graded = passed + failed
    return passed / graded * 100 if graded > 0 else None


def _graded(kind: SummaryKind, totals: _Totals) -> int:
    match kind:
        case "pass_rate":
            return totals.passed + totals.failed
        case "score":
            return totals.score_count
        case "categories":
            return totals.categorized
        case "sentiment":
            return totals.positive + totals.neutral + totals.negative


def _score(meta: EvaluationMeta, totals: _Totals) -> contracts.ScoreDistribution | None:
    if totals.score_count == 0:
        return None
    return contracts.ScoreDistribution(mean=totals.score_sum / totals.score_count, scale=meta.scale)


def _category_counts(rows: Sequence[CategoryBucketCount], current: bool) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if (row.bucket is not None) == current:
            counts[row.key] += row.runs
    return counts


def _summary(
    meta: EvaluationMeta,
    current: _Totals,
    previous: _Totals,
    categories: Sequence[CategoryBucketCount],
) -> contracts.ResultSummary:
    match meta.kind:
        case "pass_rate":
            return contracts.PassRateSummary(
                kind="pass_rate",
                passed=current.passed,
                failed=current.failed,
                previous=contracts.PassFailCounts(passed=previous.passed, failed=previous.failed)
                if previous.passed + previous.failed > 0
                else None,
                score=_score(meta, current) if meta.output_type == "numeric" else None,
            )
        case "score":
            return contracts.ScoreSummary(
                kind="score",
                score=_score(meta, current),
                previous_mean=previous.score_sum / previous.score_count if previous.score_count else None,
            )
        case "categories":
            counts = _category_counts(categories, current=True)
            previous_counts = _category_counts(categories, current=False)
            options = list(meta.categories)
            known = {option.key for option in options}
            # A category from the previous period only has dropped to zero, which can be the largest move.
            unknown = dict.fromkeys(key for key in [*counts, *previous_counts] if key and key not in known)
            options += [CategoryOption(key=key, label=key) for key in unknown]
            entries = [
                contracts.CategoryCount(
                    key=option.key,
                    label=option.label,
                    count=counts.get(option.key, 0),
                    previous_share=_share(previous_counts.get(option.key, 0), previous.categorized)
                    if previous.categorized
                    else None,
                )
                for option in options
            ]
            return contracts.CategoriesSummary(
                kind="categories",
                multiple=meta.multiple,
                categories=sorted(entries, key=lambda entry: -entry.count),
                no_categories_count=counts.get("", 0),
            )
        case "sentiment":
            total = previous.positive + previous.neutral + previous.negative
            return contracts.SentimentSummary(
                kind="sentiment",
                positive=current.positive,
                neutral=current.neutral,
                negative=current.negative,
                previous_negative_share=_share(previous.negative, total) if total else None,
            )


def has_low_evidence(graded_count: int) -> bool:
    return 0 < graded_count < LOW_EVIDENCE_GRADED_COUNT


def result_change(graded_count: int, summary: contracts.ResultSummary) -> contracts.ResultChange | None:
    """Change against the previous equal period, or None when there is nothing fair to compare."""
    if graded_count == 0 or has_low_evidence(graded_count):
        return None
    match summary:
        case contracts.PassRateSummary():
            current = pass_rate(summary.passed, summary.failed)
            previous = pass_rate(summary.previous.passed, summary.previous.failed) if summary.previous else None
            if current is None or previous is None:
                return None
            return contracts.ResultChange(value=_js_round(current - previous, 1), unit="pp", subject=None)
        case contracts.ScoreSummary():
            if summary.score is None or summary.previous_mean is None:
                return None
            return contracts.ResultChange(
                value=_js_round(summary.score.mean - summary.previous_mean, 2), unit="points", subject=None
            )
        case contracts.CategoriesSummary():
            moved = _largest_category_move(summary, graded_count)
            if moved is None:
                return None
            category, delta = moved
            return contracts.ResultChange(value=delta, unit="pp", subject=category.label)
        case contracts.SentimentSummary():
            if summary.previous_negative_share is None:
                return None
            total = summary.positive + summary.neutral + summary.negative
            return contracts.ResultChange(
                value=_js_round(_share(summary.negative, total) - summary.previous_negative_share, 1),
                unit="pp",
                subject="negative",
            )


def _largest_category_move(
    summary: contracts.CategoriesSummary, graded_count: int
) -> tuple[contracts.CategoryCount, float] | None:
    """The category that moved most, since the top category is often the stable one."""
    largest: tuple[contracts.CategoryCount, float] | None = None
    for category in summary.categories:
        if category.previous_share is None:
            continue
        delta = _js_round(_share(category.count, graded_count) - category.previous_share, 1)
        if largest is None or abs(delta) > abs(largest[1]):
            largest = (category, delta)
    return largest


def _tracked_category(
    summary: contracts.ResultSummary, change: contracts.ResultChange | None, graded_count: int
) -> contracts.CategoryCount | None:
    """The category a categorical evaluation's trend follows: the one that moved most, else the most common."""
    if not isinstance(summary, contracts.CategoriesSummary):
        return None
    # Labels need not be unique, so the trend follows the category itself and not its label.
    moved = _largest_category_move(summary, graded_count) if change is not None else None
    if moved is not None:
        return moved[0]
    return summary.categories[0] if summary.categories else None


def _previous_value(summary: contracts.ResultSummary, tracked: str | None) -> float | None:
    match summary:
        case contracts.PassRateSummary():
            return pass_rate(summary.previous.passed, summary.previous.failed) if summary.previous else None
        case contracts.ScoreSummary():
            return summary.previous_mean
        case contracts.SentimentSummary():
            return summary.previous_negative_share
        case contracts.CategoriesSummary():
            return next((category.previous_share for category in summary.categories if category.key == tracked), None)


def _bucket_index(instants: Sequence[datetime], bucket: datetime) -> int:
    """The bucket that holds a ClickHouse bucket start: the last one that starts at or before it, compared by
    instant."""
    return max(bisect_right(instants, bucket.astimezone(UTC)) - 1, 0)


def _bucket_value(
    meta: EvaluationMeta, row: _Totals | None, tracked_key: str | None, category_runs: int
) -> float | None:
    if row is None:
        return None
    match meta.kind:
        case "pass_rate":
            return pass_rate(row.passed, row.failed)
        case "score":
            return row.score_sum / row.score_count if row.score_count else None
        case "sentiment":
            total = row.positive + row.neutral + row.negative
            return _share(row.negative, total) if total else None
        case "categories":
            return _share(category_runs, row.categorized) if row.categorized and tracked_key is not None else None


def bucket_status(
    summary: contracts.ResultSummary, trend: contracts.EvaluationResultTrend, tracked: str | None
) -> list[contracts.BucketStatus]:
    """Status of each bucket against the previous period, or against the range's own median without one.

    Pass rates and sentiment have a worse direction. Scores and label shares have none, so a large move either way
    counts as unusual. A bucket with fewer graded runs than a summary needs is never flagged, because one run moves
    a thin bucket by more than the dip threshold, which hourly buckets would turn into noise.
    """
    previous = _previous_value(summary, tracked)
    typical = previous if previous is not None else _median([value for value in trend.values if value is not None])
    statuses: list[contracts.BucketStatus] = []
    for value, graded in zip(trend.values, trend.volume):
        if value is None:
            statuses.append("none")
        elif typical is None or graded < LOW_EVIDENCE_GRADED_COUNT:
            statuses.append("normal")
        else:
            statuses.append("dip" if _is_dip(summary, value, typical) else "normal")
    return statuses


def _is_dip(summary: contracts.ResultSummary, value: float, typical: float) -> bool:
    match summary:
        case contracts.PassRateSummary():
            return value <= typical - DIP_PP
        case contracts.SentimentSummary():
            return value >= typical + DIP_PP
        case contracts.CategoriesSummary():
            return abs(value - typical) >= DIP_PP
        case contracts.ScoreSummary():
            # Without configured bounds, or with equal ones, there is no scale to measure a move against.
            scale = summary.score.scale if summary.score else None
            span = scale.max - scale.min if scale else 0
            return span > 0 and abs(value - typical) >= span * SCORE_SHIFT_SHARE


def attention_reasons(
    *,
    enabled: bool,
    errored: bool,
    graded_count: int,
    summary: contracts.ResultSummary,
    change: contracts.ResultChange | None,
) -> list[contracts.AttentionReason]:
    # The error status also disables the evaluation, and that pause was not the user's choice, so it still asks for
    # attention. Its missing results follow from the error, so it is never also silent or worse.
    if errored:
        return ["errored"]
    # Pausing an evaluation is a deliberate choice, so a paused one never asks for attention.
    if not enabled:
        return []
    reasons: list[contracts.AttentionReason] = []
    if graded_count == 0:
        reasons.append("silent")
    # Only results with a clear worse direction count: a falling pass rate or a rising negative share.
    if change is not None and change.unit == "pp":
        if (isinstance(summary, contracts.PassRateSummary) and change.value <= -NOTABLE_CHANGE_PP) or (
            isinstance(summary, contracts.SentimentSummary) and change.value >= NOTABLE_CHANGE_PP
        ):
            reasons.append("worse")
    return reasons


def evaluation_result(
    meta: EvaluationMeta,
    buckets: Sequence[datetime],
    counts: Sequence[EvaluationBucketCounts],
    categories: Sequence[CategoryBucketCount],
) -> contracts.EvaluationResult:
    """`counts` and `categories` hold only this evaluation's rows, see `group_by_evaluation`."""
    instants = [bucket.astimezone(UTC) for bucket in buckets]
    by_bucket: dict[int, list[EvaluationBucketCounts]] = defaultdict(list)
    for row in counts:
        if row.bucket is not None:
            by_bucket[_bucket_index(instants, row.bucket)].append(row)
    current = _sum([row for row in counts if row.bucket is not None])
    previous = _sum([row for row in counts if row.bucket is None])
    previous_graded = _graded(meta.kind, previous)
    # A thin previous period is no fairer a baseline than a thin current one, so the summary leaves it out.
    baseline = previous if previous_graded >= LOW_EVIDENCE_GRADED_COUNT else _sum([])
    summary = _summary(meta, current, baseline, categories)
    graded_count = _graded(meta.kind, current)
    change = result_change(graded_count, summary)
    tracked = _tracked_category(summary, change, graded_count)
    tracked_key = tracked.key if tracked else None
    tracked_runs: dict[int, int] = defaultdict(int)
    for category in categories:
        if category.bucket is not None and category.key == tracked_key:
            tracked_runs[_bucket_index(instants, category.bucket)] += category.runs
    bucket_totals = [_sum(by_bucket[index]) if index in by_bucket else None for index in range(len(buckets))]
    trend = contracts.EvaluationResultTrend(
        values=[
            _bucket_value(meta, totals, tracked_key, tracked_runs[index]) for index, totals in enumerate(bucket_totals)
        ],
        volume=[_graded(meta.kind, totals) if totals is not None else 0 for totals in bucket_totals],
    )
    last_run_at = max((row.last_run_at for row in counts if row.last_run_at is not None), default=None)
    return contracts.EvaluationResult(
        id=meta.id,
        name=meta.name,
        directory_name=meta.directory_name,
        evaluation_type=meta.evaluation_type,
        output_type=meta.output_type,
        enabled=meta.enabled,
        status_reason=meta.status_reason,
        created_by=meta.created_by,
        graded_count=graded_count,
        previous_graded_count=previous_graded or None,
        not_applicable_count=current.not_applicable,
        skipped_count=current.skipped,
        last_run_at=last_run_at,
        summary=summary,
        trend=trend,
        change=change,
        low_evidence=has_low_evidence(graded_count),
        attention_reasons=attention_reasons(
            enabled=meta.enabled,
            errored=meta.errored,
            graded_count=graded_count,
            summary=summary,
            change=change,
        ),
        bucket_status=bucket_status(summary, trend, tracked_key),
        tracked_category=tracked_key,
    )


def pass_rate_overview(rows: Sequence[contracts.EvaluationResult], bucket_count: int) -> contracts.PassRateOverview:
    entries: list[contracts.PassRateOverviewEntry] = []
    measured: list[contracts.EvaluationResult] = []
    compared: list[tuple[float, float]] = []
    for row in rows:
        summary = row.summary
        if not isinstance(summary, contracts.PassRateSummary) or not row.enabled:
            continue
        rate = pass_rate(summary.passed, summary.failed)
        if rate is None:
            continue
        entries.append(contracts.PassRateOverviewEntry(evaluation_id=row.id, rate=rate, low_evidence=row.low_evidence))
        if row.low_evidence:
            continue
        measured.append(row)
        previous = pass_rate(summary.previous.passed, summary.previous.failed) if summary.previous else None
        if previous is not None:
            compared.append((rate, previous))
    median_trend = (
        [
            _median([value for row in measured if (value := row.trend.values[index]) is not None])
            for index in range(bucket_count)
        ]
        if measured
        else []
    )
    # Both medians cover the same evaluations, so a change between them is not a change in which ones ran.
    current_median = _median([current for current, _ in compared])
    previous_median = _median([previous for _, previous in compared])
    median_comparison = (
        contracts.PeriodComparison(current=current_median, previous=previous_median)
        if current_median is not None and previous_median is not None
        else None
    )
    return contracts.PassRateOverview(
        entries=sorted(entries, key=lambda entry: entry.rate),
        median=_median([entry.rate for entry in entries if not entry.low_evidence]),
        median_comparison=median_comparison,
        median_trend=median_trend,
    )


def overview_totals(rows: Sequence[contracts.EvaluationResult], bucket_count: int) -> contracts.OverviewTotals:
    """Totals for the metric cards at the top of the overview."""
    active = [row for row in rows if row.enabled]
    # Only evaluations with results in both periods, so a new or newly silent evaluation does not read as a change.
    both = [row for row in active if row.graded_count > 0 and row.previous_graded_count is not None]
    sentiment = None
    for row in active:
        if isinstance(row.summary, contracts.SentimentSummary) and row.graded_count > 0:
            summary = row.summary
            sentiment = contracts.OverviewSentiment(
                evaluation_id=row.id,
                negative_share=_share(summary.negative, summary.positive + summary.neutral + summary.negative),
                previous_share=summary.previous_negative_share,
            )
            break
    return contracts.OverviewTotals(
        graded=sum(row.graded_count for row in active),
        graded_comparison=contracts.PeriodComparison(
            current=sum(row.graded_count for row in both),
            previous=sum(row.previous_graded_count or 0 for row in both),
        )
        if both
        else None,
        graded_trend=[sum(row.trend.volume[index] for row in active) for index in range(bucket_count)]
        if active
        else [],
        sentiment=sentiment,
    )
