import pytest

from posthog.schema import (
    AlertCondition,
    AlertConditionType,
    InsightsThresholdBounds,
    InsightThreshold,
    InsightThresholdType,
    IntervalType,
)

from products.alerts.backend.evaluation.comparator import evaluate_threshold
from products.alerts.backend.evaluation.contract import ComparableSeries, ExtractionResult, SeriesPoint

ABSOLUTE = AlertCondition(type=AlertConditionType.ABSOLUTE_VALUE)
INCREASE = AlertCondition(type=AlertConditionType.RELATIVE_INCREASE)
DECREASE = AlertCondition(type=AlertConditionType.RELATIVE_DECREASE)


def _threshold(type_=InsightThresholdType.ABSOLUTE, lower=None, upper=None):
    return InsightThreshold(type=type_, bounds=InsightsThresholdBounds(lower=lower, upper=upper))


def _result(
    series,
    *,
    is_breakdown=False,
    subject="The insight value",
    framed=True,
    interval_type=None,
    empty_query_result=False,
):
    return ExtractionResult(
        series=series,
        is_breakdown=is_breakdown,
        subject=subject,
        framed=framed,
        interval_type=interval_type,
        empty_query_result=empty_query_result,
    )


def _single(value, label="A"):
    return _result([ComparableSeries(label=label, points=[SeriesPoint(date=None, value=value)], current_index=0)])


@pytest.mark.parametrize(
    "value,lower,upper,expected_message",
    [
        (50.0, 10, 100, None),  # within bounds → no breach
        (5.0, 10, None, "less than lower threshold"),
        (150.0, None, 100, "more than upper threshold"),
    ],
)
def test_absolute_breach_detection(value, lower, upper, expected_message):
    result = evaluate_threshold(_single(value), ABSOLUTE, _threshold(lower=lower, upper=upper))
    assert result.value == value
    if expected_message is None:
        assert result.breaches == []
    else:
        assert result.breaches is not None and len(result.breaches) == 1
        assert expected_message in result.breaches[0]


def test_unit_suffix_renders_in_breach_message():
    # Funnel conversion rates are absolute 0–100 values carried with a "%" unit so the notification
    # matches the configure-time UI (which shows a % suffix).
    series = [ComparableSeries(label="conversion", points=[SeriesPoint(date=None, value=40.0)], current_index=0)]
    result = ExtractionResult(series=series, subject="The funnel conversion rate", framed=False, unit="%")
    out = evaluate_threshold(result, ABSOLUTE, _threshold(lower=50))
    assert out.breaches is not None and len(out.breaches) == 1
    assert "(40.0%)" in out.breaches[0]
    assert "lower threshold (50.0%)" in out.breaches[0]


@pytest.mark.parametrize(
    "values,current_index,is_current,condition,threshold_type,upper,expected_value,expected_message",
    [
        # non-current anchor (index 1 = prev): increase = prev - prev_prev = 20 - 10
        ([10.0, 20.0, 35.0], 1, False, INCREASE, InsightThresholdType.ABSOLUTE, 5, 10.0, "increased"),
        # check_ongoing → anchor = last (current): increase = current - prev = 35 - 20
        ([10.0, 20.0, 35.0], 2, True, INCREASE, InsightThresholdType.ABSOLUTE, 5, 15.0, "current"),
        # decrease = prev_prev - prev = 20 - 8
        ([20.0, 8.0, 5.0], 1, False, DECREASE, InsightThresholdType.ABSOLUTE, 5, 12.0, "decreased"),
        # percentage: (20 - 10) / 10 = 1.0
        ([10.0, 20.0, 30.0], 1, False, INCREASE, InsightThresholdType.PERCENTAGE, 0.5, 1.0, None),
        # percentage decrease: (20 - 8) / 20 = 0.6, over the 0.5 upper bound → breach
        ([20.0, 8.0, 5.0], 1, False, DECREASE, InsightThresholdType.PERCENTAGE, 0.5, 0.6, "decreased"),
        # percentage with a zero base → inf
        ([0.0, 10.0, 20.0], 1, False, INCREASE, InsightThresholdType.PERCENTAGE, 0.5, float("inf"), None),
    ],
)
def test_relative_value_computation(
    values, current_index, is_current, condition, threshold_type, upper, expected_value, expected_message
):
    series = [
        ComparableSeries(
            label="A",
            points=[SeriesPoint(None, v) for v in values],
            current_index=current_index,
            is_current_interval=is_current,
        )
    ]
    result = evaluate_threshold(_result(series), condition, _threshold(type_=threshold_type, upper=upper))
    assert result.value == expected_value
    if expected_message is not None:
        assert result.breaches is not None and expected_message in result.breaches[0]


@pytest.mark.parametrize(
    "is_breakdown,n_series,expected_value",
    [
        (False, 1, 50.0),  # single-series query reports its computed value
        (True, 2, None),  # breakdown has no single representative value → None
        (True, 1, None),  # a one-series breakdown still reports None (keyed off is_breakdown, not count)
    ],
)
def test_no_breach_value_reporting(is_breakdown, n_series, expected_value):
    series = [
        ComparableSeries(label=f"s{i}", points=[SeriesPoint(None, 50.0)], current_index=0) for i in range(n_series)
    ]
    result = evaluate_threshold(_result(series, is_breakdown=is_breakdown), ABSOLUTE, _threshold(lower=10))
    assert result.breaches == []
    assert result.value == expected_value


@pytest.mark.parametrize(
    "threshold",
    [
        None,  # no threshold at all
        InsightThreshold(type=InsightThresholdType.ABSOLUTE, bounds=None),  # bounds=None
    ],
)
def test_missing_threshold_or_bounds_returns_zero(threshold):
    # The dispatcher short-circuits to value=0 before running the query; the comparator mirrors it.
    result = evaluate_threshold(_single(50.0), ABSOLUTE, threshold)
    assert result.breaches == []
    assert result.value == 0


def test_empty_bounds_evaluates_but_never_breaches():
    # bounds present but both None: truthy → proceeds, no lower/upper to breach → reports value.
    result = evaluate_threshold(_single(50.0), ABSOLUTE, _threshold())
    assert result.breaches == []
    assert result.value == 50.0


def test_breakdown_breaches_if_any_series_breaches():
    series = [
        ComparableSeries(label="us", points=[SeriesPoint(None, 50.0)], current_index=0),
        ComparableSeries(label="de", points=[SeriesPoint(None, 5.0)], current_index=0),
    ]
    result = evaluate_threshold(_result(series, is_breakdown=True), ABSOLUTE, _threshold(lower=10))
    assert result.breaches is not None and len(result.breaches) == 1
    assert "de" in result.breaches[0]
    assert result.value == 5.0


def test_empty_query_result_reports_zero_even_for_breakdown():
    # An empty query result reports value=0 regardless of breakdown (the metric is genuinely zero),
    # matching the original _is_empty_query_result. Without the empty_query_result flag a breakdown
    # would report None here.
    sentinel = [
        ComparableSeries(label="empty result", points=[SeriesPoint(None, 0.0), SeriesPoint(None, 0.0)], current_index=1)
    ]
    for is_breakdown in (False, True):
        result = _result(sentinel, is_breakdown=is_breakdown, empty_query_result=True)
        no_breach = evaluate_threshold(result, ABSOLUTE, _threshold(lower=-5))
        assert no_breach.breaches == []
        assert no_breach.value == 0


@pytest.mark.parametrize(
    "condition",
    [ABSOLUTE, INCREASE, DECREASE],
)
def test_empty_result_sentinel_evaluates_zero_and_can_breach(condition):
    # The extractor emits a two-zero-point sentinel for an empty result: absolute reads 0, relative
    # computes 0 - 0 = 0. A positive lower bound fires on that 0 (parity with the original).
    empty = _result(
        [
            ComparableSeries(
                label="empty result", points=[SeriesPoint(None, 0.0), SeriesPoint(None, 0.0)], current_index=1
            )
        ]
    )
    breach = evaluate_threshold(empty, condition, _threshold(lower=5))
    assert breach.value == 0.0
    assert breach.breaches is not None and len(breach.breaches) == 1
    no_breach = evaluate_threshold(empty, condition, _threshold(lower=-5))
    assert no_breach.value == 0.0
    assert no_breach.breaches == []


def test_missing_current_point_skips_series():
    series = [ComparableSeries(label="A", points=[SeriesPoint(None, None)], current_index=0)]
    result = evaluate_threshold(_result(series), ABSOLUTE, _threshold(lower=10))
    assert result.breaches == []


@pytest.mark.parametrize(
    "points,current_index",
    [
        ([], -1),  # empty series, anchor_is_current branch → current_index = len-1 = -1
        ([], -2),  # empty series, non-current branch → current_index = len-2 = -2
        ([SeriesPoint(None, 5.0)], -1),  # single-point series in the non-current branch → len-2 = -1
        ([SeriesPoint(None, 5.0)], 1),  # current_index past the end
    ],
)
def test_out_of_bounds_anchor_skips_series_without_crashing(points, current_index):
    # A degenerate series (empty, or too short for the chosen anchor) must be skipped, not indexed —
    # otherwise s.points[current_index] raises IndexError and the whole alert check errors out.
    series = [ComparableSeries(label="A", points=points, current_index=current_index)]
    result = evaluate_threshold(_result(series), ABSOLUTE, _threshold(lower=10))
    assert result.breaches == []


def test_framed_message_includes_series_and_interval():
    series = [ComparableSeries(label="US", points=[SeriesPoint(None, 5.0)], current_index=0)]
    result = evaluate_threshold(_result(series, interval_type=IntervalType.DAY), ABSOLUTE, _threshold(lower=10))
    assert result.breaches is not None
    assert result.breaches[0] == "The insight value (US) for previous day (5.0) is less than lower threshold (10.0)"


def test_unframed_message_uses_subject_without_interval_framing():
    series = [ComparableSeries(label="result", points=[SeriesPoint(None, 5.0)], current_index=0)]
    result = evaluate_threshold(
        _result(series, subject="The SQL insight value", framed=False), ABSOLUTE, _threshold(lower=10)
    )
    assert result.breaches is not None
    assert result.breaches[0] == "The SQL insight value (5.0) is less than lower threshold (10.0)"
    assert "interval" not in result.breaches[0]


def test_value_formatter_formats_both_value_and_bounds():
    # A trends value_formatter renders the breach value AND the threshold bound (currency here).
    series = [ComparableSeries(label="A", points=[SeriesPoint(None, 5.0)], current_index=0)]
    result = ExtractionResult(series=series, value_formatter=lambda v: f"${v:,.2f}")
    out = evaluate_threshold(result, ABSOLUTE, _threshold(lower=10))
    assert out.breaches is not None
    assert (
        out.breaches[0] == "The insight value (A) for previous interval ($5.00) is less than lower threshold ($10.00)"
    )


def test_percentage_threshold_ignores_value_formatter():
    # A relative % alert renders its change ratio as its own %, taking precedence over any formatter.
    series = [ComparableSeries(label="A", points=[SeriesPoint(None, v) for v in (10.0, 20.0)], current_index=1)]
    result = ExtractionResult(series=series, value_formatter=lambda v: f"${v:,.2f}")
    out = evaluate_threshold(result, INCREASE, _threshold(type_=InsightThresholdType.PERCENTAGE, upper=0.5))
    assert out.breaches is not None
    assert "100.00%" in out.breaches[0]
    assert "$" not in out.breaches[0]
