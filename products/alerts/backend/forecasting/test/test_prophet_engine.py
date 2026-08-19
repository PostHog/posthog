import datetime

import pytest

import numpy as np
from parameterized import parameterized

from posthog.schema import IntervalType

from products.alerts.backend.forecasting.engine import (
    MAX_FORECAST_LOOKBACK_DAYS,
    MAX_FORECAST_REACH_DAYS,
    ForecastResult,
    bounded_training_points,
    forecast_reach_days,
    get_forecast_engine,
    horizon_for_target_date,
    intervals_between,
    max_evaluable_horizon,
)


def _daily_dates(n: int) -> list[str]:
    start = datetime.date(2026, 1, 1)
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(n)]


class TestProphetEngine:
    def test_registry_returns_prophet_engine(self):
        engine = get_forecast_engine({"type": "ForecastConfig", "engine": "prophet"})
        assert engine is not None

    def test_registry_rejects_unknown_engine(self):
        with pytest.raises(ValueError):
            get_forecast_engine({"type": "ForecastConfig", "engine": "nonsense"})

    def test_forecast_shape(self):
        np.random.seed(42)
        engine = get_forecast_engine({"engine": "prophet"})
        values = [float(100 + 2 * i) for i in range(60)]
        result = engine.forecast(_daily_dates(60), values, horizon=7, interval_width=0.95, interval=IntervalType.DAY)
        assert isinstance(result, ForecastResult)
        assert len(result.dates) == len(result.yhat) == len(result.lower) == len(result.upper) == 7
        assert result.dates[0].startswith("2026-03-02")

    @parameterized.expand(
        [
            ("upward_trend", [float(100 + 2 * i) for i in range(60)], lambda fc: fc.yhat[-1] > 210),
            ("flat", [100.0] * 60, lambda fc: abs(fc.yhat[-1] - 100.0) < 10),
        ]
    )
    def test_forecast_follows_trend(self, _name, values, check):
        np.random.seed(42)
        engine = get_forecast_engine({"engine": "prophet"})
        result = engine.forecast(_daily_dates(60), values, horizon=7, interval_width=0.95, interval=IntervalType.DAY)
        assert check(result)

    def test_band_contains_point_forecast(self):
        np.random.seed(42)
        engine = get_forecast_engine({"engine": "prophet"})
        values = [float(100 + 2 * i + (5 if i % 7 == 0 else 0)) for i in range(60)]
        result = engine.forecast(_daily_dates(60), values, horizon=7, interval_width=0.95, interval=IntervalType.DAY)
        for i in range(7):
            assert result.lower[i] <= result.yhat[i] <= result.upper[i]

    def test_fit_quality_and_components_populated(self):
        np.random.seed(42)
        engine = get_forecast_engine({"engine": "prophet"})
        values = [float(100 + 2 * i + (-1) ** i * 0.3) for i in range(60)]
        result = engine.forecast(
            _daily_dates(60), values, horizon=7, interval_width=0.95, interval=IntervalType.DAY, include_history=True
        )
        assert result.fit_mape is not None and result.fit_mape < 0.1
        assert result.fit_coverage is not None and result.fit_coverage > 0.8
        assert result.components is not None
        assert len(result.components["trend"]) == 7

    def test_history_band_is_opt_in_and_aligned(self):
        np.random.seed(42)
        engine = get_forecast_engine({"engine": "prophet"})
        values = [float(100 + 2 * i + (-1) ** i * 0.3) for i in range(60)]
        dates = _daily_dates(60)

        without = engine.forecast(dates, values, horizon=7, interval_width=0.95, interval=IntervalType.DAY)
        assert without.history_lower is None
        assert without.history_upper is None
        assert without.fit_mape is None and without.fit_coverage is None

        with_history = engine.forecast(
            dates, values, horizon=7, interval_width=0.95, interval=IntervalType.DAY, include_history=True
        )
        assert with_history.history_lower is not None and len(with_history.history_lower) == len(values)
        assert with_history.history_upper is not None and len(with_history.history_upper) == len(values)
        assert len(with_history.dates) == len(without.dates) == 7


class TestForecastReach:
    @parameterized.expand(
        [
            ("daily", IntervalType.DAY, datetime.date(2026, 3, 31), 30),
            ("weekly", IntervalType.WEEK, datetime.date(2026, 3, 31), 5),
            ("monthly", IntervalType.MONTH, datetime.date(2026, 6, 1), 4),
            ("hourly", IntervalType.HOUR, datetime.date(2026, 3, 3), 48),
            ("none_defaults_to_daily", None, datetime.date(2026, 3, 31), 30),
        ]
    )
    def test_horizon_for_target_date(self, _name, interval, target, expected) -> None:
        assert horizon_for_target_date(target, interval, datetime.date(2026, 3, 1)) == expected

    def test_horizon_rejects_a_past_date(self) -> None:
        with pytest.raises(ValueError, match="in the future"):
            horizon_for_target_date(datetime.date(2026, 2, 1), IntervalType.DAY, datetime.date(2026, 3, 1))

    def test_horizon_rejects_a_date_beyond_the_cap(self) -> None:
        with pytest.raises(ValueError, match="within 6 months"):
            horizon_for_target_date(datetime.date(2027, 3, 1), IntervalType.DAY, datetime.date(2026, 3, 1))

    @parameterized.expand(
        [
            ("30 days is fine", 30, IntervalType.DAY, True),
            ("30 weeks reaches 7 months", 30, IntervalType.WEEK, False),
            ("30 months reaches 2.5 years", 30, IntervalType.MONTH, False),
            ("6 months of weeks is fine", 26, IntervalType.WEEK, True),
        ]
    )
    def test_forecast_reach_days_bounds_every_condition(self, _name, horizon, interval, within_cap) -> None:
        assert (forecast_reach_days(horizon, interval) <= MAX_FORECAST_REACH_DAYS) is within_cap

    @parameterized.expand(
        [
            ("hourly caps on fit cost", 17569, IntervalType.HOUR, 1000),
            ("monthly caps on duration", 91, IntervalType.MONTH, 24),
            ("daily caps on duration", 733, IntervalType.DAY, 730),
            ("a small window is untouched", 91, IntervalType.DAY, 91),
            ("never below the fit minimum", 1, IntervalType.HOUR, 48),
        ]
    )
    def test_bounded_training_points(self, _name, requested, interval, expected) -> None:
        assert bounded_training_points(requested, interval) == expected

    def test_no_interval_scans_more_than_two_years(self) -> None:
        for interval in (IntervalType.HOUR, IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH):
            points = bounded_training_points(1_000_000, interval)
            assert forecast_reach_days(points, interval) <= MAX_FORECAST_LOOKBACK_DAYS

    @parameterized.expand(
        [
            ("daily, one day back", IntervalType.DAY, 1),
            ("weekly, just after a boundary", IntervalType.WEEK, 7),
            ("weekly, just before one", IntervalType.WEEK, 13),
            ("monthly, short gap", IntervalType.MONTH, 28),
            ("monthly, long gap", IntervalType.MONTH, 61),
        ]
    )
    def test_evaluation_reaches_any_date_save_accepted(self, _name, interval, bucket_age_days) -> None:
        today = datetime.date(2026, 3, 1)
        furthest_saveable = today + datetime.timedelta(days=MAX_FORECAST_REACH_DAYS)
        horizon_for_target_date(furthest_saveable, interval, today)

        last_bucket = today - datetime.timedelta(days=bucket_age_days)
        horizon = intervals_between(last_bucket, furthest_saveable, interval)
        assert horizon <= max_evaluable_horizon(interval)
