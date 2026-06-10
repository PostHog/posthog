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


def _threshold(type_=InsightThresholdType.ABSOLUTE, lower=None, upper=None):
    return InsightThreshold(type=type_, bounds=InsightsThresholdBounds(lower=lower, upper=upper))


def _result(series, *, is_breakdown=False, subject="The insight value", framed=True, interval_type=None):
    return ExtractionResult(
        series=series, is_breakdown=is_breakdown, subject=subject, framed=framed, interval_type=interval_type
    )


def _single(value, label="A"):
    return _result([ComparableSeries(label=label, points=[SeriesPoint(date=None, value=value)], current_index=0)])


ABSOLUTE = AlertCondition(type=AlertConditionType.ABSOLUTE_VALUE)
INCREASE = AlertCondition(type=AlertConditionType.RELATIVE_INCREASE)
DECREASE = AlertCondition(type=AlertConditionType.RELATIVE_DECREASE)


def test_absolute_within_bounds_no_breach():
    result = evaluate_threshold(_single(50.0), ABSOLUTE, _threshold(lower=10, upper=100))
    assert result.breaches == []
    assert result.value == 50.0


def test_absolute_below_lower_breaches():
    result = evaluate_threshold(_single(5.0), ABSOLUTE, _threshold(lower=10))
    assert len(result.breaches) == 1
    assert "less than lower threshold" in result.breaches[0]
    assert result.value == 5.0


def test_absolute_above_upper_breaches():
    result = evaluate_threshold(_single(150.0), ABSOLUTE, _threshold(upper=100))
    assert len(result.breaches) == 1
    assert "more than upper threshold" in result.breaches[0]


def test_unset_bounds_returns_zero_no_breach():
    # bounds=None (not merely empty) is the trends.py guard that short-circuits to value=0.
    result = evaluate_threshold(
        _single(50.0), ABSOLUTE, InsightThreshold(type=InsightThresholdType.ABSOLUTE, bounds=None)
    )
    assert result.breaches == []
    assert result.value == 0


def test_empty_bounds_evaluates_but_never_breaches():
    # bounds present but both None: truthy → proceeds, no lower/upper to breach → reports value.
    result = evaluate_threshold(_single(50.0), ABSOLUTE, _threshold())
    assert result.breaches == []
    assert result.value == 50.0


def test_none_threshold_returns_zero():
    result = evaluate_threshold(_single(50.0), ABSOLUTE, None)
    assert result.breaches == []
    assert result.value == 0


def test_breakdown_breaches_if_any_series_breaches():
    series = [
        ComparableSeries(label="us", points=[SeriesPoint(None, 50.0)], current_index=0),
        ComparableSeries(label="de", points=[SeriesPoint(None, 5.0)], current_index=0),
    ]
    result = evaluate_threshold(_result(series, is_breakdown=True), ABSOLUTE, _threshold(lower=10))
    assert len(result.breaches) == 1
    assert "de" in result.breaches[0]
    assert result.value == 5.0


def test_breakdown_no_breach_reports_none_value():
    series = [
        ComparableSeries(label="us", points=[SeriesPoint(None, 50.0)], current_index=0),
        ComparableSeries(label="de", points=[SeriesPoint(None, 60.0)], current_index=0),
    ]
    result = evaluate_threshold(_result(series, is_breakdown=True), ABSOLUTE, _threshold(lower=10))
    assert result.breaches == []
    assert result.value is None


def test_single_value_breakdown_no_breach_still_reports_none():
    # A breakdown that returns exactly one series must still report value=None, not the value —
    # the original keyed this off has_breakdown, not series count.
    series = [ComparableSeries(label="us", points=[SeriesPoint(None, 50.0)], current_index=0)]
    result = evaluate_threshold(_result(series, is_breakdown=True), ABSOLUTE, _threshold(lower=10))
    assert result.breaches == []
    assert result.value is None


def test_non_breakdown_no_breach_reports_value():
    result = evaluate_threshold(_single(50.0), ABSOLUTE, _threshold(lower=10))
    assert result.breaches == []
    assert result.value == 50.0


def test_empty_result_sentinel_absolute_compares_zero():
    # The extractor emits a two-zero-point sentinel for an empty result; absolute reads 0.
    empty = _result(
        [
            ComparableSeries(
                label="empty result", points=[SeriesPoint(None, 0.0), SeriesPoint(None, 0.0)], current_index=1
            )
        ]
    )
    breach = evaluate_threshold(empty, ABSOLUTE, _threshold(lower=10))
    assert len(breach.breaches) == 1 and breach.value == 0.0
    no_breach = evaluate_threshold(empty, ABSOLUTE, _threshold(lower=-5))
    assert no_breach.breaches == [] and no_breach.value == 0.0


def test_empty_result_sentinel_relative_computes_zero_and_can_breach():
    # Two zero points → relative delta 0 - 0 = 0; a positive lower bound fires (parity with the original).
    empty = _result(
        [
            ComparableSeries(
                label="empty result", points=[SeriesPoint(None, 0.0), SeriesPoint(None, 0.0)], current_index=1
            )
        ]
    )
    breach = evaluate_threshold(empty, INCREASE, _threshold(lower=5))
    assert len(breach.breaches) == 1 and breach.value == 0.0
    assert evaluate_threshold(empty, DECREASE, _threshold(lower=5)).value == 0.0


def test_relative_increase_absolute_delta():
    # points ascending [prev_prev=10, prev=20, current=35], non-current anchor (index 1 = prev):
    # increase = prev - prev_prev = 20 - 10 = 10
    series = [
        ComparableSeries(
            label="A",
            points=[SeriesPoint(None, 10.0), SeriesPoint(None, 20.0), SeriesPoint(None, 35.0)],
            current_index=1,
        )
    ]
    result = evaluate_threshold(_result(series), INCREASE, _threshold(upper=5))
    assert result.value == 10.0
    assert "increased" in result.breaches[0]


def test_relative_increase_current_interval_anchor_last():
    # check_ongoing → anchor=last (current=35): increase = current - prev = 35 - 20 = 15
    series = [
        ComparableSeries(
            label="A",
            points=[SeriesPoint(None, 10.0), SeriesPoint(None, 20.0), SeriesPoint(None, 35.0)],
            current_index=2,
            is_current_interval=True,
        )
    ]
    result = evaluate_threshold(_result(series), INCREASE, _threshold(upper=5))
    assert result.value == 15.0
    assert "current" in result.breaches[0]


def test_relative_decrease_absolute_delta():
    # anchor=index 1=prev=8, previous=prev_prev=20: decrease = prev_prev - prev = 20 - 8 = 12
    series = [
        ComparableSeries(
            label="A", points=[SeriesPoint(None, 20.0), SeriesPoint(None, 8.0), SeriesPoint(None, 5.0)], current_index=1
        )
    ]
    result = evaluate_threshold(_result(series), DECREASE, _threshold(upper=5))
    assert result.value == 12.0
    assert "decreased" in result.breaches[0]


def test_relative_increase_percentage():
    # anchor=prev=20, previous=prev_prev=10: pct = (20-10)/10 = 1.0 (100%)
    series = [
        ComparableSeries(
            label="A",
            points=[SeriesPoint(None, 10.0), SeriesPoint(None, 20.0), SeriesPoint(None, 30.0)],
            current_index=1,
        )
    ]
    result = evaluate_threshold(_result(series), INCREASE, _threshold(type_=InsightThresholdType.PERCENTAGE, upper=0.5))
    assert result.value == 1.0


def test_relative_percentage_zero_base_is_inf():
    series = [
        ComparableSeries(
            label="A",
            points=[SeriesPoint(None, 0.0), SeriesPoint(None, 10.0), SeriesPoint(None, 20.0)],
            current_index=1,
        )
    ]
    result = evaluate_threshold(_result(series), INCREASE, _threshold(type_=InsightThresholdType.PERCENTAGE, upper=0.5))
    assert result.value == float("inf")


def test_missing_current_point_skips_series():
    series = [ComparableSeries(label="A", points=[SeriesPoint(None, None)], current_index=0)]
    result = evaluate_threshold(_result(series), ABSOLUTE, _threshold(lower=10))
    assert result.breaches == []


def test_framed_message_includes_series_and_interval():
    series = [ComparableSeries(label="US", points=[SeriesPoint(None, 5.0)], current_index=0)]
    result = evaluate_threshold(_result(series, interval_type=IntervalType.DAY), ABSOLUTE, _threshold(lower=10))
    assert result.breaches[0] == "The insight value (US) for previous day (5.0) is less than lower threshold (10.0)"


def test_unframed_message_uses_subject_without_interval_framing():
    series = [ComparableSeries(label="result", points=[SeriesPoint(None, 5.0)], current_index=0)]
    result = evaluate_threshold(
        _result(series, subject="The SQL insight value", framed=False), ABSOLUTE, _threshold(lower=10)
    )
    assert result.breaches[0] == "The SQL insight value (5.0) is less than lower threshold (10.0)"
    assert "interval" not in result.breaches[0]
