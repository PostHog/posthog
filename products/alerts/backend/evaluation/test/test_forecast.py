import datetime

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    ForecastConditionType,
    ForecastConfig,
    ForecastSensitivity,
    ForecastTargetDirection,
    InsightsThresholdBounds,
    InsightThreshold,
    InsightThresholdType,
    IntervalType,
)

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ComparableSeries,
    ExtractionResult,
    InsufficientHistoryError,
    SeriesPoint,
)
from products.alerts.backend.evaluation.forecast import (
    _decomposition_suffix,
    _evaluate_future_breach_values,
    _evaluate_target_by_date_values,
    _index_for_target_date,
    _latest_deviation,
    _required_points,
    _resolve_sensitivity,
    evaluate_with_forecast,
)
from products.alerts.backend.forecasting.engine import ForecastResult


class StubEngine:
    def __init__(self, result: ForecastResult):
        self._result = result
        self.calls: list[dict] = []

    def forecast(self, dates, values, horizon, interval_width, interval, include_history=False):
        self.calls.append({"dates": dates, "values": values, "horizon": horizon, "interval_width": interval_width})
        return self._result


def _series(n: int = 30, value: float = 100.0) -> ExtractionResult:
    start = datetime.date(2026, 1, 1)
    points = [SeriesPoint(date=(start + datetime.timedelta(days=i)).isoformat(), value=value) for i in range(n)]
    return ExtractionResult(
        series=[ComparableSeries(label="pageviews", points=points, current_index=n - 1)],
        interval_type=IntervalType.DAY,
    )


def _threshold(lower=None, upper=None) -> InsightThreshold:
    return InsightThreshold(
        type=InsightThresholdType.ABSOLUTE, bounds=InsightsThresholdBounds(lower=lower, upper=upper)
    )


def _fc(yhat: list[float], pad: float = 5.0) -> ForecastResult:
    return ForecastResult(
        dates=[f"2026-02-{i + 1:02d}T00:00:00" for i in range(len(yhat))],
        yhat=yhat,
        lower=[v - pad for v in yhat],
        upper=[v + pad for v in yhat],
    )


class TestEvaluateWithForecast:
    @parameterized.expand(
        [
            ("upper_breach", [100.0, 120.0, 160.0], None, 150.0, True),
            ("lower_breach", [100.0, 80.0, 40.0], 50.0, None, True),
            ("no_breach", [100.0, 101.0, 102.0], 50.0, 150.0, False),
        ]
    )
    def test_future_breach(self, _name, yhat, lower, upper, should_fire):
        config = {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach", "horizon": 3}
        stub = StubEngine(_fc(yhat))
        with patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=stub):
            result = evaluate_with_forecast(_series(), config, _threshold(lower=lower, upper=upper))
        assert bool(result.breaches) is should_fire
        assert stub.calls[0]["horizon"] == 3
        if should_fire:
            assert result.triggered_metadata is not None
            assert "forecast" in result.triggered_metadata

    @parameterized.expand(
        [
            ("inside_band", 100.0, False),
            ("above_band", 200.0, True),
            ("below_band", 10.0, True),
        ]
    )
    def test_band_deviation(self, _name, latest_actual, should_fire):
        config = {"type": "ForecastConfig", "engine": "prophet", "condition": "band_deviation"}
        extraction = _series(30)
        extraction.series[0].points[-1] = SeriesPoint(date="2026-01-30", value=latest_actual)
        stub = StubEngine(_fc([100.0]))  # band [95, 105]
        with patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=stub):
            result = evaluate_with_forecast(extraction, config, None)
        assert bool(result.breaches) is should_fire
        assert result.value == latest_actual
        # band_deviation fits on history excluding the evaluated point
        assert len(stub.calls[0]["values"]) == 29

    @parameterized.expand(
        [
            ("future_breach_below_minimum", "future_breach", 5),
            # band_deviation holds out the latest point as the actual, fitting on one fewer point —
            # so it needs min_points + 1 (15), not min_points (14), to have a full fitting window.
            ("band_deviation_at_min_points_boundary", "band_deviation", 14),
        ]
    )
    def test_insufficient_history_raises(self, _name, condition, n_points):
        config = {"type": "ForecastConfig", "engine": "prophet", "condition": condition}
        # Not AlertExtractionError: that path disables the alert and emails subscribers that it is
        # misconfigured, which is wrong for an insight that is merely young.
        with pytest.raises(InsufficientHistoryError, match="history"):
            evaluate_with_forecast(_series(n_points), config, _threshold(upper=1.0))

    def test_unknown_condition_raises(self):
        config = {"type": "ForecastConfig", "engine": "prophet", "condition": "bogus_condition"}
        with pytest.raises(AlertExtractionError, match="Unknown forecast condition"):
            evaluate_with_forecast(_series(), config, _threshold(upper=1.0))

    def test_empty_query_result_is_zero_value_no_breach(self):
        config = {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach"}
        result = evaluate_with_forecast(
            ExtractionResult(series=[], empty_query_result=True, interval_type=IntervalType.DAY),
            config,
            _threshold(upper=1.0),
        )
        assert result.value == 0
        assert result.breaches == []


class TestLatestDeviation:
    @parameterized.expand(
        [
            ("future_breach_pays_nothing", "future_breach", None),
            ("band_deviation_computes", "band_deviation", True),
        ]
    )
    def test_only_band_deviation_runs_a_second_fit(self, _name: str, condition: str, expected: bool | None) -> None:
        engine = StubEngine(_fc([100.0]))
        result = _latest_deviation(
            ["2026-02-01", "2026-02-02"], [100.0, 120.0], {"condition": condition}, engine, 0.95, IntervalType.DAY
        )
        assert (result is not None) == (expected is not None)
        assert len(engine.calls) == (1 if expected else 0)

    @parameterized.expand(
        [
            ("inside", 100.0, False),
            ("above", 200.0, True),
            ("below", 10.0, True),
        ]
    )
    def test_outside_matches_the_held_out_band(self, _name: str, latest: float, outside: bool) -> None:
        # Band is 95..105 from _fc([100.0], pad=5). The held-out fit excludes the latest point, which
        # is what _evaluate_band_deviation does, so preview and evaluation agree by construction.
        engine = StubEngine(_fc([100.0]))
        result = _latest_deviation(
            ["2026-02-01", "2026-02-02"], [100.0, latest], {"condition": "band_deviation"}, engine, 0.95, None
        )
        assert result is not None
        assert result["outside"] is outside
        assert result["value"] == latest
        assert engine.calls[0]["values"] == [100.0]


def test_target_config_parses_with_defaults() -> None:
    parsed = ForecastConfig.model_validate(
        {
            "type": "ForecastConfig",
            "engine": "prophet",
            "condition": "target_by_date",
            "target": 10000,
            "target_direction": "at_least",
            "target_date": "2026-12-31",
        }
    )
    assert parsed.condition == ForecastConditionType.TARGET_BY_DATE
    assert parsed.target == 10000
    assert parsed.target_direction == ForecastTargetDirection.AT_LEAST
    # Unset rather than defaulted in the schema: the evaluator resolves it to best_case, so a
    # saved alert never carries a sensitivity it did not choose.
    assert parsed.sensitivity is None
    assert ForecastSensitivity.BEST_CASE.value == "best_case"


class TestTargetByDate:
    @parameterized.expand(
        [
            # (direction, sensitivity, yhat, lower, upper, target, should_fire)
            ("at_least misses on forecast", "at_least", "forecast", 90.0, 70.0, 110.0, 100.0, True),
            ("at_least holds on forecast", "at_least", "forecast", 110.0, 90.0, 130.0, 100.0, False),
            # best_case is quieter: the optimistic edge still clears the target.
            ("at_least holds on best case", "at_least", "best_case", 90.0, 70.0, 110.0, 100.0, False),
            ("at_least misses on best case", "at_least", "best_case", 80.0, 60.0, 95.0, 100.0, True),
            ("at_most misses on forecast", "at_most", "forecast", 110.0, 90.0, 130.0, 100.0, True),
            ("at_most holds on best case", "at_most", "best_case", 110.0, 90.0, 130.0, 100.0, False),
            ("at_most misses on best case", "at_most", "best_case", 130.0, 105.0, 150.0, 100.0, True),
        ]
    )
    def test_target_by_date_fires(self, _name, direction, sensitivity, yhat, lower, upper, target, should_fire) -> None:
        result = _evaluate_target_by_date_values(
            yhat=yhat,
            lower=lower,
            upper=upper,
            target=target,
            direction=direction,
            sensitivity=sensitivity,
            target_date="2026-12-31",
            label="A",
        )
        assert bool(result.breaches) is should_fire

    @parameterized.expand(
        [
            ("unset defaults to best case", {}, "best_case"),
            ("explicit forecast is kept", {"sensitivity": "forecast"}, "forecast"),
            ("explicit best case is kept", {"sensitivity": "best_case"}, "best_case"),
        ]
    )
    def test_resolve_sensitivity(self, _name, config, expected) -> None:
        assert _resolve_sensitivity(config) == expected


class TestFutureBreachSensitivity:
    @parameterized.expand(
        [
            # Upper bound 100. The point forecast crosses it; the favorable edge (lower) does not.
            ("upper: forecast crosses", "forecast", 105.0, 95.0, 130.0, {"upper": 100.0}, True),
            ("upper: best case holds", "best_case", 105.0, 95.0, 130.0, {"upper": 100.0}, False),
            # Once even the favorable edge is past the bound, best_case fires too.
            ("upper: best case crosses", "best_case", 110.0, 105.0, 140.0, {"upper": 100.0}, True),
            # Lower bound 100, mirrored: the favorable edge against a floor is the upper one.
            ("lower: forecast crosses", "forecast", 95.0, 70.0, 105.0, {"lower": 100.0}, True),
            ("lower: best case holds", "best_case", 95.0, 70.0, 105.0, {"lower": 100.0}, False),
            ("lower: best case crosses", "best_case", 90.0, 60.0, 95.0, {"lower": 100.0}, True),
        ]
    )
    def test_sensitivity_picks_the_compared_edge(
        self, _name, sensitivity, yhat, lower, upper, bounds, should_fire
    ) -> None:
        result = _evaluate_future_breach_values(
            yhat=[yhat],
            lower=[lower],
            upper=[upper],
            dates=["2026-04-01"],
            bounds=InsightsThresholdBounds(**bounds),
            sensitivity=sensitivity,
            label="A",
            horizon=7,
        )
        assert bool(result.breaches) is should_fire

    @parameterized.expand(
        [
            # future_breach exists for lead time, so its default stays on the point forecast.
            ("future_breach defaults to forecast", "future_breach", "forecast"),
            ("target_by_date defaults to best case", "target_by_date", "best_case"),
            ("band_deviation is unaffected", "band_deviation", "best_case"),
        ]
    )
    def test_default_sensitivity_depends_on_condition(self, _name, condition, expected) -> None:
        assert _resolve_sensitivity({"condition": condition}) == expected
        # An explicit choice always wins over the per-condition default.
        assert _resolve_sensitivity({"condition": condition, "sensitivity": "forecast"}) == "forecast"


class TestPreviewMatchesEvaluation:
    @parameterized.expand(
        [
            # band_deviation holds out the latest point, so it needs one more than the others.
            ("band_deviation needs one extra", "band_deviation", IntervalType.DAY, 15),
            ("future_breach does not", "future_breach", IntervalType.DAY, 14),
            ("target_by_date does not", "target_by_date", IntervalType.DAY, 14),
            ("hourly needs two days of points", "future_breach", IntervalType.HOUR, 48),
            ("hourly band_deviation needs one more", "band_deviation", IntervalType.HOUR, 49),
        ]
    )
    def test_required_points_is_shared_by_preview_and_evaluation(self, _name, condition, interval, expected) -> None:
        # The preview used to require one fewer point than evaluation for band_deviation, so an
        # alert at exactly the minimum previewed clean and then errored on its first real check.
        assert _required_points(condition, interval) == expected


class TestTargetDateIndex:
    @parameterized.expand(
        [
            # Prophet extends from the last completed bucket, so the run can end on or past the
            # date. Picking [-1] evaluated the day before the one the user asked about.
            ("lands exactly", ["2026-03-29", "2026-03-30", "2026-03-31"], "2026-03-31", 2),
            ("overshoots", ["2026-03-30", "2026-03-31", "2026-04-01"], "2026-03-31", 1),
            ("iso timestamps", ["2026-03-30T00:00:00", "2026-03-31T00:00:00"], "2026-03-31", 1),
            ("falls short, takes the last", ["2026-03-28", "2026-03-29"], "2026-03-31", 1),
        ]
    )
    def test_index_for_target_date(self, _name, forecast_dates, target, expected) -> None:
        assert _index_for_target_date(forecast_dates, target) == expected


class TestInsufficientHistoryIsNotMisconfiguration:
    def test_a_young_insight_does_not_raise_the_disabling_error(self) -> None:
        """AlertExtractionError routes to disable_invalid_alert, which turns the alert off and
        emails subscribers that it is misconfigured. A young insight is neither."""
        result = _series(n=3)
        with pytest.raises(InsufficientHistoryError):
            evaluate_with_forecast(result, {"condition": "future_breach"}, None)
        # The distinction is the point: it must not be catchable as a configuration failure.
        assert not issubclass(InsufficientHistoryError, AlertExtractionError)


class TestDecompositionCopy:
    def _forecast(self, trend: float, weekly: float) -> ForecastResult:
        return ForecastResult(
            dates=["2026-04-01"],
            yhat=[100.0],
            lower=[90.0],
            upper=[110.0],
            components={"trend": [trend], "weekly": [weekly]},
        )

    def test_states_the_direction_in_the_metric_terms(self) -> None:
        assert _decomposition_suffix(self._forecast(1210.0, -145.2), 0) == (
            " (usual level around 1,210, typically 12% lower on this day of the week)"
        )

    def test_a_negative_trend_states_no_seasonality_rather_than_the_opposite(self) -> None:
        """Dividing by a negative trend flips the sign, so a component that is lower would read as
        higher. Opaque model output made that survivable; a plain sentence would not."""
        suffix = _decomposition_suffix(self._forecast(-1000.0, -120.0), 0)
        assert "higher" not in suffix
        assert "lower" not in suffix
        assert suffix == " (usual level around -1,000)"
