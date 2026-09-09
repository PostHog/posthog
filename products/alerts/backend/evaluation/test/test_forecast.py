import datetime
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    ForecastConfig,
    InsightsThresholdBounds,
    InsightThreshold,
    InsightThresholdType,
    IntervalType,
    TrendsQuery,
)

from posthog.api.services.query import ExecutionMode
from posthog.models.team import Team
from posthog.tasks.alerts.detector import _date_range_override_for_detector

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ComparableSeries,
    ExtractionResult,
    InsufficientHistoryError,
    SeriesPoint,
    SimulationContext,
)
from products.alerts.backend.evaluation.detector import extract_trends_series
from products.alerts.backend.evaluation.dispatcher import check_forecast_alert
from products.alerts.backend.evaluation.forecast import (
    TrendsForecastExtractor,
    _forecast_extraction_contract,
    _index_for_target_date,
    _target_projection,
    evaluate_with_forecast,
    simulate_forecast_on_insight,
)
from products.alerts.backend.evaluation.validation import validate_alert_config
from products.alerts.backend.forecasting.capacity import ForecastEvaluationCapacityExceeded
from products.alerts.backend.forecasting.engine import ForecastConfigurationError, ForecastResult
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


class StubEngine:
    def __init__(self, result: ForecastResult):
        self._result = result
        self.calls: list[dict] = []

    def forecast(self, dates, values, horizon, interval_width, interval, timezone="UTC"):
        self.calls.append(
            {
                "dates": dates,
                "values": values,
                "horizon": horizon,
                "interval_width": interval_width,
                "interval": interval,
                "timezone": timezone,
            }
        )
        return self._result


class ConfigurationErrorEngine:
    def forecast(self, dates, values, horizon, interval_width, interval, timezone="UTC"):
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

    def test_a_monthly_forecast_without_a_horizon_stays_within_the_reach_cap(self) -> None:
        engine = StubEngine(_forecast(["2026-04-01", "2026-05-01", "2026-06-01"], [90.0, 90.0, 90.0]))

        with patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=engine):
            evaluate_with_forecast(
                _series(n=14, interval=IntervalType.MONTH),
                {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach"},
                _threshold(upper=1000.0),
            )

        assert engine.calls[0]["horizon"] == 3

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


class TestTargetHorizonContract:
    @parameterized.expand(
        [
            ("daily", IntervalType.DAY, "2026-10-07", datetime.date(2026, 9, 6), 31),
            ("weekly stops before a midweek target", IntervalType.WEEK, "2026-11-04", datetime.date(2026, 8, 31), 9),
            (
                "weekly reaches a target on a bucket start",
                IntervalType.WEEK,
                "2026-11-09",
                datetime.date(2026, 8, 31),
                10,
            ),
            ("monthly counts calendar months", IntervalType.MONTH, "2026-11-04", datetime.date(2026, 8, 1), 3),
        ]
    )
    def test_the_horizon_stops_at_the_last_bucket_on_or_before_the_target(
        self, _name: str, interval: IntervalType, target_date: str, anchor: datetime.date, expected: int
    ) -> None:
        config = {
            "type": "ForecastConfig",
            "engine": "prophet",
            "condition": "target_by_date",
            "target": 100,
            "target_direction": "at_least",
            "target_date": target_date,
        }
        now = datetime.datetime(2026, 9, 7, 12, 0, tzinfo=datetime.UTC)

        horizon, reference_date = _forecast_extraction_contract(config, interval, now, week_start_day=1)

        assert (horizon, reference_date) == (expected, anchor)


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

    def test_a_repeated_bucket_label_is_collapsed_before_fitting(self) -> None:
        extraction = _series(49, interval=IntervalType.HOUR)
        points = extraction.series[0].points
        points[25].date = points[24].date
        points[25].value = 123.0

        engine = StubEngine(_forecast(["2026-01-03T01:00:00"], [90.0]))
        with patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=engine):
            result = evaluate_with_forecast(
                extraction,
                {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach", "horizon": 3},
                _threshold(upper=1000),
            )

        assert result.is_inconclusive is False
        dates = engine.calls[0]["dates"]
        values = engine.calls[0]["values"]
        assert len(dates) == len(set(dates)) == 48
        assert len(values) == 48
        assert values[dates.index(points[24].date)] == 123.0

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

    def test_target_history_is_sized_from_the_last_completed_bucket(self) -> None:
        forecast_config = {
            "type": "ForecastConfig",
            "engine": "prophet",
            "condition": "target_by_date",
            "target": 100,
            "target_direction": "at_least",
            "target_date": "2026-10-07",
        }
        team = SimpleNamespace(timezone="UTC", week_start_day=1, base_currency="USD")
        alert = SimpleNamespace(
            forecast_config=forecast_config,
            config={"series_index": 0},
            team=team,
            created_by=None,
        )
        query = {
            "kind": "TrendsQuery",
            "interval": "day",
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
        }
        extraction = _series(n=124, start=datetime.date(2026, 5, 6))
        engine = StubEngine(_forecast(["2026-10-07"], [100.0]))

        with (
            freeze_time("2026-09-07T12:00:00Z"),
            patch(
                "products.alerts.backend.evaluation.forecast.extract_trends_series", return_value=extraction
            ) as extract,
            patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=engine),
        ):
            result = TrendsForecastExtractor().extract(
                cast(AlertConfiguration, alert),
                cast(Insight, SimpleNamespace()),
                query,
                ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            )
            evaluation = evaluate_with_forecast(result, forecast_config, None)

        assert extract.call_args.args[3] == 124
        assert evaluation.is_inconclusive is False
        assert engine.calls[0]["horizon"] == 31

    @parameterized.expand([("scheduled check", False), ("preview", True)])
    def test_a_null_interval_asks_for_daily_history(self, _name: str, is_preview: bool) -> None:
        forecast_config = {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach", "horizon": 7}
        team = SimpleNamespace(timezone="UTC", week_start_day=1, base_currency="USD")
        query = {
            "kind": "TrendsQuery",
            "interval": None,
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
        }

        with (
            freeze_time("2026-09-07T12:00:00Z"),
            patch(
                "products.alerts.backend.evaluation.forecast.extract_trends_series", return_value=_series()
            ) as extract,
        ):
            if is_preview:
                context = SimulationContext(team=cast(Team, team), extractor_config=forecast_config)
                TrendsForecastExtractor().simulate(cast(Insight, SimpleNamespace()), query, context)
            else:
                alert = SimpleNamespace(
                    forecast_config=forecast_config,
                    config={"series_index": 0},
                    team=team,
                    created_by=None,
                )
                TrendsForecastExtractor().extract(
                    cast(AlertConfiguration, alert),
                    cast(Insight, SimpleNamespace()),
                    query,
                    ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                )

        requested_query, min_samples = extract.call_args.args[2], extract.call_args.args[3]
        assert _date_range_override_for_detector(requested_query, min_samples) == {"date_from": "-28d"}

    @parameterized.expand(
        [
            (
                "target pins a bucket, so it needs fresh data",
                {
                    "condition": "target_by_date",
                    "target": 100,
                    "target_direction": "at_least",
                    "target_date": "2026-10-07",
                },
                ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            ),
            (
                "breach keeps the shared cached mode",
                {"condition": "future_breach", "horizon": 7},
                ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            ),
        ]
    )
    def test_the_execution_mode_reaching_the_query(
        self, _name: str, condition: dict, expected_mode: ExecutionMode
    ) -> None:
        forecast_config = {"type": "ForecastConfig", "engine": "prophet", **condition}
        alert = SimpleNamespace(
            forecast_config=forecast_config,
            config={"series_index": 0},
            team=SimpleNamespace(timezone="UTC", week_start_day=1, base_currency="USD"),
            created_by=None,
        )
        query = {
            "kind": "TrendsQuery",
            "interval": "day",
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
        }

        with (
            freeze_time("2026-09-07T12:00:00Z"),
            patch(
                "products.alerts.backend.evaluation.forecast.extract_trends_series",
                return_value=_series(n=124, start=datetime.date(2026, 5, 6)),
            ) as extract,
        ):
            TrendsForecastExtractor().extract(
                cast(AlertConfiguration, alert),
                cast(Insight, SimpleNamespace()),
                query,
                ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            )

        assert extract.call_args.args[4] == expected_mode


def test_scheduled_forecast_capacity_is_deferred_without_extracting() -> None:
    alert = cast(
        AlertConfiguration,
        SimpleNamespace(
            forecast_config={"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach"},
            threshold=None,
            team_id=123,
            is_high_frequency_interval=False,
        ),
    )
    query = {
        "kind": "TrendsQuery",
        "interval": "day",
        "series": [{"kind": "EventsNode", "event": "$pageview"}],
    }
    extractor = MagicMock()
    unavailable_slot = MagicMock()
    unavailable_slot.return_value.__enter__.side_effect = ForecastEvaluationCapacityExceeded

    with (
        patch("products.alerts.backend.evaluation.dispatcher.forecast_evaluation_slot", unavailable_slot),
        patch("products.alerts.backend.evaluation.dispatcher.FORECAST_EXTRACTORS", {"TrendsQuery": extractor}),
        pytest.raises(ForecastEvaluationCapacityExceeded),
    ):
        check_forecast_alert(alert, cast(Insight, SimpleNamespace()), query)

    unavailable_slot.assert_called_once_with(team_id=123)
    extractor.extract.assert_not_called()


def test_forecast_extraction_disables_comparison_in_the_execution_query() -> None:
    query = TrendsQuery.model_validate(
        {
            "kind": "TrendsQuery",
            "interval": "day",
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
            "compareFilter": {"compare": True},
        }
    )
    calculation = SimpleNamespace(result=[])

    with patch(
        "products.alerts.backend.evaluation.detector.calculate_for_query_based_insight", return_value=calculation
    ) as calculate:
        extract_trends_series(
            cast(Insight, SimpleNamespace(id=1)),
            SimpleNamespace(),
            query,
            min_samples=14,
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        )

    execution_query = calculate.call_args.kwargs["query_override"]
    assert execution_query["compareFilter"]["compare"] is False


def test_forecast_simulation_rejects_smoothed_trends_before_extraction() -> None:
    insight = cast(
        Insight,
        SimpleNamespace(
            query={
                "kind": "TrendsQuery",
                "interval": "day",
                "series": [{"kind": "EventsNode", "event": "$pageview"}],
                "trendsFilter": {"display": "ActionsLineGraph", "smoothingIntervals": 3},
            }
        ),
    )
    team = cast(Team, SimpleNamespace(timezone="UTC", base_currency="USD"))

    with (
        patch("products.alerts.backend.evaluation.forecast.extract_trends_series") as extract,
        pytest.raises(ValueError, match="smoothed trends"),
    ):
        simulate_forecast_on_insight(
            insight,
            team,
            {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach", "horizon": 1},
        )

    extract.assert_not_called()


def test_forecast_validation_rejects_smoothed_trends() -> None:
    query = {
        "kind": "TrendsQuery",
        "interval": "day",
        "series": [{"kind": "EventsNode", "event": "$pageview"}],
        "trendsFilter": {"display": "ActionsLineGraph", "smoothingIntervals": 3},
    }

    with pytest.raises(ValueError, match="smoothed trends"):
        validate_alert_config(
            query=query,
            condition={"type": "absolute_value"},
            config={"type": "TrendsAlertConfig", "series_index": 0},
            threshold_config={"type": "absolute", "bounds": {"upper": 100}},
            calculation_interval="daily",
            forecast_config={
                "type": "ForecastConfig",
                "engine": "prophet",
                "condition": "future_breach",
                "horizon": 7,
            },
        )


@parameterized.expand(
    [
        (
            "hourly target",
            "hour",
            "ActionsLineGraph",
            {
                "type": "ForecastConfig",
                "engine": "prophet",
                "condition": "target_by_date",
                "target": 100,
                "target_direction": "at_least",
                "target_date": "2026-10-01",
            },
            "hourly",
        ),
        (
            "cumulative trend",
            "day",
            "ActionsLineGraphCumulative",
            {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach"},
            "cumulative",
        ),
        (
            "calendar heatmap",
            "day",
            "CalendarHeatmap",
            {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach"},
            "calendar heatmap, box plot, or slope graph",
        ),
        (
            "box plot",
            "day",
            "BoxPlot",
            {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach"},
            "calendar heatmap, box plot, or slope graph",
        ),
        (
            "slope graph",
            "day",
            "SlopeGraph",
            {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach"},
            "calendar heatmap, box plot, or slope graph",
        ),
    ]
)
def test_forecast_validation_rejects_ambiguous_query_semantics(
    _name: str, interval: str, display: str, forecast_config: dict, message: str
) -> None:
    query = {
        "kind": "TrendsQuery",
        "interval": interval,
        "series": [{"kind": "EventsNode", "event": "$pageview"}],
        "trendsFilter": {"display": display},
    }
    with freeze_time("2026-09-07T12:00:00Z"), pytest.raises(ValueError, match=message):
        validate_alert_config(
            query=query,
            condition={"type": "absolute_value"},
            config={"type": "TrendsAlertConfig", "series_index": 0},
            threshold_config={"type": "absolute", "bounds": {"upper": 100}},
            calculation_interval="daily",
            forecast_config=forecast_config,
            require_future_target_date=True,
            project_timezone="UTC",
        )


class TestForecastSimulationLookback:
    def test_preview_fits_the_same_trailing_history_as_a_scheduled_check(self) -> None:
        extraction = _series(n=90)
        engine = StubEngine(_forecast(["2026-04-01"], [90.0]))
        insight = cast(
            Insight,
            SimpleNamespace(
                query={
                    "kind": "TrendsQuery",
                    "interval": "day",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                }
            ),
        )
        team = cast(Team, SimpleNamespace(timezone="UTC", week_start_day=1, base_currency="USD"))

        with (
            patch("products.alerts.backend.evaluation.forecast.extract_trends_series", return_value=extraction),
            patch("products.alerts.backend.evaluation.forecast.get_forecast_engine", return_value=engine),
        ):
            result = simulate_forecast_on_insight(
                insight,
                team,
                {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach", "horizon": 7},
                date_from="-90d",
            )

        assert len(result["data"]) == 90
        assert engine.calls[0]["dates"] == [point.date for point in extraction.series[0].points[-28:]]

    @parameterized.expand(
        [
            ("absolute_too_old", "day", "1900-01-01", "2024-09-07"),
            ("relative_too_old", "day", "-100y", "2024-09-07"),
            ("within_limit", "day", "-30d", "-30d"),
            ("exact_limit", "day", "2024-09-07", "2024-09-07"),
            ("weekly_still_caps_on_duration", "week", "1900-01-01", "2024-09-07"),
            ("hourly_caps_on_fit_cost", "hour", "-730d", "2026-07-27"),
            ("hourly_within_limit", "hour", "-7d", "-7d"),
        ]
    )
    def test_query_date_from_is_capped_before_extraction(
        self, _name: str, interval: str, date_from: str, expected_date_from: str
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
            "interval": interval,
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


@parameterized.expand([("calendar heatmap", "CalendarHeatmap"), ("box plot", "BoxPlot"), ("slope graph", "SlopeGraph")])
def test_forecast_simulation_rejects_specialized_runner_displays(_name: str, display: str) -> None:
    insight = cast(
        Insight,
        SimpleNamespace(
            query={
                "kind": "TrendsQuery",
                "interval": "day",
                "series": [{"kind": "EventsNode", "event": "$pageview"}],
                "trendsFilter": {"display": display},
            }
        ),
    )
    team = cast(Team, SimpleNamespace(timezone="UTC", base_currency="USD"))

    with (
        patch("products.alerts.backend.evaluation.forecast.extract_trends_series") as extract,
        pytest.raises(ValueError, match="calendar heatmap, box plot, or slope graph"),
    ):
        simulate_forecast_on_insight(
            insight,
            team,
            {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach", "horizon": 1},
        )

    extract.assert_not_called()
