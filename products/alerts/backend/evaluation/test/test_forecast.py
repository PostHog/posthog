import datetime
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from freezegun import freeze_time
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import ForecastConfig, InsightsThresholdBounds, InsightThreshold, InsightThresholdType, IntervalType

from posthog.models.team import Team

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ComparableSeries,
    ExtractionResult,
    InsufficientHistoryError,
    SeriesPoint,
    SimulationContext,
)
from products.alerts.backend.evaluation.forecast import (
    TrendsForecastExtractor,
    _index_for_target_date,
    _target_projection,
    evaluate_with_forecast,
)
from products.alerts.backend.forecasting.engine import ForecastConfigurationError, ForecastResult
from products.product_analytics.backend.facade.models import Insight


class StubEngine:
    def __init__(self, result: ForecastResult):
        self._result = result
        self.calls: list[dict] = []

    def forecast(self, dates, values, horizon, interval_width, interval):
        self.calls.append(
            {
                "dates": dates,
                "values": values,
                "horizon": horizon,
                "interval_width": interval_width,
                "interval": interval,
            }
        )
        return self._result


class ConfigurationErrorEngine:
    def forecast(self, dates, values, horizon, interval_width, interval):
        raise ForecastConfigurationError("invalid engine input")


def _series(
    n: int = 40,
    value: float = 90.0,
    *,
    start: datetime.date = datetime.date(2026, 1, 1),
    interval: IntervalType = IntervalType.DAY,
    value_formatter: Callable[[float], str] | None = None,
) -> ExtractionResult:
    step = datetime.timedelta(hours=1) if interval == IntervalType.HOUR else datetime.timedelta(days=1)
    points = [
        SeriesPoint(
            date=(datetime.datetime.combine(start, datetime.time()) + step * index).isoformat(),
            value=value,
        )
        for index in range(n)
    ]
    return ExtractionResult(
        series=[ComparableSeries(label="pageviews", points=points, current_index=n - 1)],
        interval_type=interval,
        value_formatter=value_formatter,
    )


def _threshold(lower: float | None = None, upper: float | None = None) -> InsightThreshold:
    return InsightThreshold(
        type=InsightThresholdType.ABSOLUTE,
        bounds=InsightsThresholdBounds(lower=lower, upper=upper),
    )


def _forecast(dates: list[str], yhat: list[float], pad: float = 5.0) -> ForecastResult:
    return ForecastResult(
        dates=dates,
        yhat=yhat,
        lower=[value - pad for value in yhat],
        upper=[value + pad for value in yhat],
    )


class TestPredictedThresholdBreach:
    def test_engine_configuration_error_becomes_a_permanent_alert_configuration_error(self) -> None:
        with patch(
            "products.alerts.backend.evaluation.forecast.get_forecast_engine",
            return_value=ConfigurationErrorEngine(),
        ):
            with pytest.raises(AlertExtractionError, match="invalid engine input"):
                evaluate_with_forecast(
                    _series(),
                    {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach", "horizon": 1},
                    _threshold(upper=1000),
                )

    def test_an_existing_actual_breach_fires_without_running_prophet(self) -> None:
        extraction = _series(value=90.0, value_formatter=lambda value: f"${value:,.2f}")
        extraction.series[0].points[-1] = SeriesPoint(date="2026-02-09", value=120.0)
        engine = StubEngine(_forecast(["2026-02-10"], [90.0]))

        with patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=engine):
            result = evaluate_with_forecast(
                extraction,
                {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach", "horizon": 7},
                _threshold(upper=100.0),
            )

        assert result.value == 120.0
        assert result.triggered_metadata == {
            "forecast": {"breach_type": "observed", "actual_date": "2026-02-09", "actual_value": 120.0}
        }
        assert result.breaches == [
            "The latest value for pageviews ($120.00) is more than the upper threshold ($100.00)."
        ]
        assert engine.calls == []

    def test_first_point_forecast_outside_the_bound_fires(self) -> None:
        engine = StubEngine(
            _forecast(
                ["2026-02-10T00:00:00", "2026-02-11T00:00:00", "2026-02-12T00:00:00"],
                [95.0, 105.0, 110.0],
            )
        )

        with patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=engine):
            result = evaluate_with_forecast(
                _series(value_formatter=lambda value: f"{value:.1f} users"),
                {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach", "horizon": 3},
                _threshold(upper=100.0),
            )

        assert result.value == 105.0
        assert result.triggered_metadata == {
            "forecast": {
                "breach_type": "predicted",
                "breach_date": "2026-02-11T00:00:00",
                "predicted_value": 105.0,
                "lower": 100.0,
                "upper": 110.0,
                "horizon": 3,
            }
        }
        assert result.breaches == [
            "The forecast for pageviews is 105.0 users on 2026-02-11, more than the upper threshold (100.0 users)."
        ]

    @parameterized.expand(
        [
            ("upper", None, 100.0, 100.0),
            ("lower", 80.0, None, 80.0),
        ]
    )
    def test_touching_a_bound_does_not_fire(
        self, _name: str, lower: float | None, upper: float | None, predicted: float
    ) -> None:
        engine = StubEngine(_forecast(["2026-02-10"], [predicted]))
        with patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=engine):
            result = evaluate_with_forecast(
                _series(),
                {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach", "horizon": 1},
                _threshold(lower=lower, upper=upper),
            )
        assert result.breaches == []


class TestTargetByDate:
    @parameterized.expand(
        [
            ("at least misses", "at_least", 120.0, 110.0, True),
            ("at least holds", "at_least", 100.0, 110.0, False),
            ("at most misses", "at_most", 100.0, 110.0, True),
            ("at most holds", "at_most", 120.0, 110.0, False),
        ]
    )
    def test_target_compares_only_the_point_forecast(
        self, _name: str, direction: str, target: float, predicted: float, should_fire: bool
    ) -> None:
        engine = StubEngine(
            ForecastResult(
                dates=["2026-02-15T00:00:00"],
                yhat=[predicted],
                lower=[predicted - 1000],
                upper=[predicted + 1000],
            )
        )
        extraction = _series(start=datetime.date(2026, 1, 1), value_formatter=lambda value: f"${value:,.0f}")

        with patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=engine):
            result = evaluate_with_forecast(
                extraction,
                {
                    "type": "ForecastConfig",
                    "engine": "prophet",
                    "condition": "target_by_date",
                    "target": target,
                    "target_direction": direction,
                    "target_date": "2026-02-15",
                },
                None,
            )

        assert bool(result.breaches) is should_fire

    def test_target_uses_the_latest_forecast_bucket_on_or_before_the_date(self) -> None:
        engine = StubEngine(
            _forecast(
                ["2026-02-08T00:00:00", "2026-02-15T00:00:00", "2026-02-22T00:00:00"],
                [100.0, 110.0, 130.0],
            )
        )
        with patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=engine):
            result = evaluate_with_forecast(
                _series(start=datetime.date(2026, 1, 1), value_formatter=lambda value: f"{value:.0f}"),
                {
                    "type": "ForecastConfig",
                    "engine": "prophet",
                    "condition": "target_by_date",
                    "target": 120,
                    "target_direction": "at_least",
                    "target_date": "2026-02-18",
                },
                None,
            )

        assert result.value == 110.0
        assert result.triggered_metadata == {
            "forecast": {
                "target": 120.0,
                "target_date": "2026-02-18",
                "evaluated_date": "2026-02-15T00:00:00",
                "predicted_value": 110.0,
                "direction": "at_least",
            }
        }
        assert result.breaches == [
            "The forecast for pageviews is 110 on 2026-02-15, below the target of 120 for 2026-02-18."
        ]


class TestTargetDateIndex:
    @parameterized.expand(
        [
            ("exact", ["2026-03-29", "2026-03-30", "2026-03-31"], "2026-03-31", 2),
            ("between buckets", ["2026-03-30", "2026-04-06"], "2026-04-02", 0),
            ("after last bucket", ["2026-03-28", "2026-03-29"], "2026-03-31", 1),
            ("compact date", ["2026-03-30", "2026-04-06"], "20260402", 0),
            ("iso week date", ["2026-03-30", "2026-04-06"], "2026-W14-4", 0),
        ]
    )
    def test_index_for_target_date(self, _name: str, forecast_dates: list[str], target: str, expected: int) -> None:
        assert _index_for_target_date(forecast_dates, target) == expected

    def test_target_before_first_forecast_bucket_is_invalid(self) -> None:
        with pytest.raises(InsufficientHistoryError, match="completed forecast bucket"):
            _index_for_target_date(["2026-04-06"], "2026-04-02")

    def test_simulation_target_projection_reports_an_invalid_bucket_as_user_input(self) -> None:
        config = ForecastConfig.model_validate(
            {
                "type": "ForecastConfig",
                "engine": "prophet",
                "condition": "target_by_date",
                "target": 100,
                "target_direction": "at_least",
                "target_date": "2026-04-02",
            }
        ).root
        with pytest.raises(ValueError, match="completed forecast bucket"):
            _target_projection(_forecast(["2026-04-06"], [90.0]), config)


class TestHistoryRequirements:
    @parameterized.expand(
        [
            ("daily base minimum", IntervalType.DAY, 3, 13, 14),
            ("hourly base minimum", IntervalType.HOUR, 3, 47, 48),
            ("four history points per forecast point", IntervalType.DAY, 8, 31, 32),
        ]
    )
    def test_insufficient_history_is_inconclusive(
        self, _name: str, interval: IntervalType, horizon: int, insufficient: int, sufficient: int
    ) -> None:
        config = {
            "type": "ForecastConfig",
            "engine": "prophet",
            "condition": "future_breach",
            "horizon": horizon,
        }
        result = evaluate_with_forecast(_series(insufficient, interval=interval), config, _threshold(upper=1000))
        assert result.is_inconclusive is True
        assert result.triggered_metadata == {"forecast": {"status": "inconclusive", "reason": "not_enough_history"}}

        engine = StubEngine(_forecast(["2026-03-01"], [90.0]))
        with patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=engine):
            evaluate_with_forecast(_series(sufficient, interval=interval), config, _threshold(upper=1000))

    def test_empty_results_are_inconclusive_instead_of_a_zero_clear(self) -> None:
        result = evaluate_with_forecast(
            ExtractionResult(series=[], empty_query_result=True, interval_type=IntervalType.DAY),
            {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach"},
            _threshold(upper=100),
        )
        assert result.is_inconclusive is True
        assert result.value is None
        assert result.breaches == []

    def test_stale_data_cannot_hide_a_long_effective_target_horizon(self) -> None:
        engine = StubEngine(_forecast(["2026-06-01"], [90.0]))
        with patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=engine):
            result = evaluate_with_forecast(
                _series(start=datetime.date(2025, 1, 1)),
                {
                    "type": "ForecastConfig",
                    "engine": "prophet",
                    "condition": "target_by_date",
                    "target": 100,
                    "target_direction": "at_least",
                    "target_date": "2026-06-01",
                },
                None,
            )
        assert result.is_inconclusive is True
        assert result.triggered_metadata == {"forecast": {"status": "inconclusive", "reason": "stale_data"}}


class TestForecastSimulationLookback:
    @parameterized.expand(
        [
            ("absolute_too_old", "1900-01-01", "2024-09-07"),
            ("relative_too_old", "-100y", "2024-09-07"),
            ("within_limit", "-30d", "-30d"),
            ("exact_limit", "2024-09-07", "2024-09-07"),
        ]
    )
    def test_query_date_from_is_capped_before_extraction(
        self, _name: str, date_from: str, expected_date_from: str
    ) -> None:
        team = cast(Team, SimpleNamespace(timezone="UTC", base_currency="USD"))
        context = SimulationContext(
            team=team,
            extractor_config={
                "type": "ForecastConfig",
                "engine": "prophet",
                "condition": "future_breach",
                "horizon": 1,
            },
            date_from=date_from,
        )
        query = {
            "kind": "TrendsQuery",
            "interval": "day",
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
        }

        with (
            freeze_time("2026-09-07T12:00:00Z"),
            patch(
                "products.alerts.backend.evaluation.forecast.extract_trends_series", return_value=_series()
            ) as extract,
        ):
            TrendsForecastExtractor().simulate(cast(Insight, SimpleNamespace()), query, context)

        assert extract.call_args.kwargs["date_from"] == expected_date_from

    def test_excessive_relative_date_is_rejected_before_extraction(self) -> None:
        context = SimulationContext(
            team=cast(Team, SimpleNamespace(timezone="UTC", base_currency="USD")),
            extractor_config={
                "type": "ForecastConfig",
                "engine": "prophet",
                "condition": "future_breach",
                "horizon": 1,
            },
            date_from="-99999999999999999999999999999999999999999999999999y",
        )
        query = {
            "kind": "TrendsQuery",
            "interval": "day",
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
        }

        with (
            patch("products.alerts.backend.evaluation.forecast.extract_trends_series") as extract,
            pytest.raises(ValueError, match="date range is invalid"),
        ):
            TrendsForecastExtractor().simulate(cast(Insight, SimpleNamespace()), query, context)

        extract.assert_not_called()
