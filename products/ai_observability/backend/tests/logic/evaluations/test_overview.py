from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.ai_observability.backend.facade import contracts
from products.ai_observability.backend.logic.evaluations.overview import (
    CategoryOption,
    EvaluationMeta,
    SummaryKind,
    evaluation_result,
    overview_totals,
    pass_rate_overview,
)
from products.ai_observability.backend.logic.evaluations.overview_queries import (
    CategoryBucketCount,
    EvaluationBucketCounts,
)

BUCKETS = [datetime(2026, 3, day, tzinfo=UTC) for day in (1, 2, 3, 4)]


def _meta(kind: SummaryKind = "pass_rate", **fields: Any) -> EvaluationMeta:
    defaults: dict[str, Any] = {
        "id": "eval-1",
        "name": "Example",
        "directory_name": None,
        "evaluation_type": "llm_judge",
        "output_type": {"pass_rate": "boolean", "score": "numeric", "categories": "categorical"}.get(kind, kind),
        "enabled": True,
        "errored": False,
        "status_reason": None,
        "created_by": None,
        "kind": kind,
        "scale": None,
        "score_step": None,
        "categories": (),
        "multiple": False,
    }
    return EvaluationMeta(**{**defaults, **fields})


def _bucket(bucket: datetime | None, **counts: int | float) -> EvaluationBucketCounts:
    fields: dict[str, Any] = {
        "passed": 0,
        "failed": 0,
        "not_applicable": 0,
        "skipped": 0,
        "score_count": 0,
        "score_sum": 0.0,
        "categorized": 0,
        "positive": 0,
        "neutral": 0,
        "negative": 0,
        **counts,
    }
    return EvaluationBucketCounts(evaluation_id="eval-1", bucket=bucket, last_run_at=None, **fields)


def _result(
    meta: EvaluationMeta, counts: list[EvaluationBucketCounts], categories: list[CategoryBucketCount] | None = None
) -> contracts.EvaluationResult:
    return evaluation_result(meta, BUCKETS, counts, categories or [])


@parameterized.expand(
    [
        ("healthy", {}, [_bucket(BUCKETS[0], passed=90, failed=10), _bucket(None, passed=90, failed=10)], []),
        ("paused never asks", {"enabled": False}, [_bucket(None, passed=90, failed=10)], []),
        ("silent", {}, [], ["silent"]),
        # The error status disables the evaluation, so it has no results, but it is neither silent nor ignored.
        ("errored", {"enabled": False, "errored": True}, [_bucket(None, passed=80, failed=20)], ["errored"]),
        (
            "pass rate fell 2pp",
            {},
            [_bucket(BUCKETS[0], passed=88, failed=12), _bucket(None, passed=90, failed=10)],
            ["worse"],
        ),
        (
            "pass rate fell under 2pp",
            {},
            [_bucket(BUCKETS[0], passed=89, failed=11), _bucket(None, passed=90, failed=10)],
            [],
        ),
        (
            "thin previous period is never worse",
            {},
            [_bucket(BUCKETS[0], passed=450, failed=50), _bucket(None, passed=2)],
            [],
        ),
    ]
)
def test_attention_reasons(
    _name: str, meta: dict[str, Any], counts: list[EvaluationBucketCounts], expected: list[str]
) -> None:
    assert _result(_meta(**meta), counts).attention_reasons == expected


@parameterized.expand(
    [
        ("compared", [_bucket(BUCKETS[0], passed=80, failed=20), _bucket(None, passed=85, failed=15)], -5.0, False),
        (
            "low evidence is not compared",
            [_bucket(BUCKETS[0], passed=7, failed=5), _bucket(None, passed=9, failed=1)],
            None,
            True,
        ),
        ("nothing before", [_bucket(BUCKETS[0], passed=80, failed=20)], None, False),
        (
            "thin previous period is not compared",
            [_bucket(BUCKETS[0], passed=450, failed=50), _bucket(None, passed=2)],
            None,
            False,
        ),
        # 50 - 49.75 rounds half up like Math.round, where Python's round() would give 0.2.
        (
            "rounds half up",
            [_bucket(BUCKETS[0], passed=40, failed=40), _bucket(None, passed=199, failed=201)],
            0.3,
            False,
        ),
    ]
)
def test_pass_rate_change_and_low_evidence(
    _name: str, counts: list[EvaluationBucketCounts], change: float | None, low_evidence: bool
) -> None:
    result = _result(_meta(), counts)
    assert (result.change.value if result.change else None) == change
    assert result.low_evidence is low_evidence


def test_bucket_status_against_previous_period() -> None:
    result = _result(
        _meta(),
        [
            _bucket(BUCKETS[0], passed=90, failed=10),
            _bucket(BUCKETS[1], passed=86, failed=14),
            # Further below the previous rate, but too thin to judge.
            _bucket(BUCKETS[3], passed=20, failed=5),
            _bucket(None, passed=90, failed=10),
        ],
    )
    assert result.trend.values == [90.0, 86.0, None, 80.0]
    assert result.bucket_status == ["normal", "dip", "none", "normal"]


def test_bucket_status_falls_back_to_own_median_without_previous_period() -> None:
    result = _result(
        _meta(),
        [
            _bucket(BUCKETS[0], passed=90, failed=10),
            _bucket(BUCKETS[1], passed=90, failed=10),
            _bucket(BUCKETS[2], passed=80, failed=20),
        ],
    )
    assert result.bucket_status == ["normal", "normal", "dip", "none"]


def test_score_summary() -> None:
    meta = _meta("score", scale=contracts.ScoreScale(min=0, max=1))
    result = _result(
        meta,
        [
            _bucket(BUCKETS[0], score_count=40, score_sum=32.0),
            _bucket(BUCKETS[1], score_count=40, score_sum=32.0),
            _bucket(None, score_count=40, score_sum=26.0),
        ],
    )
    assert isinstance(result.summary, contracts.ScoreSummary)
    assert result.summary.score == contracts.ScoreDistribution(mean=0.8, scale=meta.scale)
    assert result.change == contracts.ResultChange(value=0.15, unit="points", subject=None)
    # A score moving 0.05 of its scale counts as unusual either way, with no worse direction.
    assert result.bucket_status == ["dip", "dip", "none", "none"]
    assert result.attention_reasons == []


def test_categories_summary_tracks_the_label_that_moved_most() -> None:
    meta = _meta(
        "categories",
        multiple=True,
        categories=(CategoryOption(key="billing", label="Billing"), CategoryOption(key="bug", label="Bug")),
    )
    categories = [
        CategoryBucketCount(evaluation_id="eval-1", bucket=BUCKETS[0], key="billing", runs=30),
        CategoryBucketCount(evaluation_id="eval-1", bucket=BUCKETS[0], key="bug", runs=12),
        CategoryBucketCount(evaluation_id="eval-1", bucket=BUCKETS[0], key="", runs=8),
        CategoryBucketCount(evaluation_id="eval-1", bucket=None, key="billing", runs=30),
        CategoryBucketCount(evaluation_id="eval-1", bucket=None, key="bug", runs=2),
        CategoryBucketCount(evaluation_id="eval-1", bucket=None, key="refund", runs=4),
    ]
    result = _result(meta, [_bucket(BUCKETS[0], categorized=50), _bucket(None, categorized=40)], categories)
    assert result.summary == contracts.CategoriesSummary(
        kind="categories",
        multiple=True,
        categories=[
            contracts.CategoryCount(key="billing", label="Billing", count=30, previous_share=75.0),
            contracts.CategoryCount(key="bug", label="Bug", count=12, previous_share=5.0),
            contracts.CategoryCount(key="refund", label="refund", count=0, previous_share=10.0),
        ],
        no_categories_count=8,
    )
    assert result.change == contracts.ResultChange(value=19.0, unit="pp", subject="Bug")
    assert result.tracked_category == "bug"
    assert result.trend.values == [24.0, None, None, None]


def test_rising_negative_sentiment_is_worse() -> None:
    result = _result(
        _meta("sentiment"),
        [_bucket(BUCKETS[0], positive=20, neutral=20, negative=10), _bucket(None, positive=25, neutral=20, negative=5)],
    )
    assert result.change == contracts.ResultChange(value=10.0, unit="pp", subject="negative")
    assert result.attention_reasons == ["worse"]


def test_overview_totals_compare_only_evaluations_with_results_in_both_periods() -> None:
    steady = _result(_meta(), [_bucket(BUCKETS[0], passed=60, failed=20), _bucket(None, passed=40, failed=10)])
    new = _result(_meta(), [_bucket(BUCKETS[1], passed=30, failed=0)])
    sentiment = _result(
        _meta("sentiment"), [_bucket(BUCKETS[1], negative=5, neutral=15), _bucket(None, negative=3, neutral=27)]
    )
    paused = _result(_meta(enabled=False), [_bucket(BUCKETS[0], passed=1000), _bucket(None, passed=1000)])

    totals = overview_totals([steady, new, sentiment, paused], len(BUCKETS))

    assert totals.graded == 1130
    assert totals.graded_comparison == contracts.PeriodComparison(current=1100, previous=1080)
    assert totals.graded_trend == [1080, 50, 0, 0]
    assert totals.sentiment == contracts.OverviewSentiment(
        evaluation_id="eval-1", negative_share=25.0, previous_share=10.0
    )
    assert overview_totals([new], len(BUCKETS)).graded_comparison is None


def test_pass_rate_median_change_uses_the_same_evaluations_in_both_periods() -> None:
    steady = _result(
        _meta(enabled=False), [_bucket(BUCKETS[0], passed=80, failed=20), _bucket(None, passed=90, failed=10)]
    )
    new = _result(_meta(), [_bucket(BUCKETS[0], passed=40, failed=60)])

    overview = pass_rate_overview([steady, new], len(BUCKETS))

    assert overview.median == 60.0
    assert overview.median_comparison == contracts.PeriodComparison(current=80.0, previous=90.0)
