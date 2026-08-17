import datetime

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import InsightsThresholdBounds, InsightThreshold, InsightThresholdType, IntervalType

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
)
from products.alerts.backend.evaluation.forecast import _latest_deviation, evaluate_with_forecast
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
        with pytest.raises(AlertExtractionError, match="history"):
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
