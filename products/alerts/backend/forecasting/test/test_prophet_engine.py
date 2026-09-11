import os
import math
import logging
import datetime
from dataclasses import fields
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from structlog.testing import capture_logs

from posthog.schema import DateRange, ForecastConfig, IntervalType

from products.alerts.backend.forecasting.engine import (
    MAX_FORECAST_LOOKBACK_DAYS,
    MAX_FORECAST_REACH_DAYS,
    ForecastConfigurationError,
    ForecastExecutionError,
    ForecastResult,
    bounded_training_points,
    default_horizon,
    forecast_reach_days,
    get_forecast_engine,
    horizon_for_target_date,
    min_forecast_points,
    validate_forecast_days_of_week,
    validate_forecast_horizon,
)


def _daily_dates(n: int) -> list[str]:
    start = datetime.date(2026, 1, 1)
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _weekly_dates(n: int, start: datetime.date) -> list[str]:
    return [(start + datetime.timedelta(weeks=i)).isoformat() for i in range(n)]


class TestProphetEngine:
    def test_registry_returns_prophet_engine(self):
        engine = get_forecast_engine({"type": "ForecastConfig", "engine": "prophet"})
        assert engine is not None

    def test_registry_rejects_unknown_engine(self):
        with pytest.raises(ValueError):
            get_forecast_engine({"type": "ForecastConfig", "engine": "nonsense"})

    def test_forecast_shape_and_structured_log(self):
        engine = get_forecast_engine({"engine": "prophet", "condition": "future_breach"})
        values = [float(100 + 2 * i) for i in range(60)]
        with capture_logs() as logs:
            result = engine.forecast(
                _daily_dates(60), values, horizon=7, interval_width=0.95, interval=IntervalType.DAY
            )
        assert isinstance(result, ForecastResult)
        assert len(result.dates) == len(result.yhat) == len(result.lower) == len(result.upper) == 7
        assert result.dates[0].startswith("2026-03-02")
        assert logs == [
            {
                "condition": "future_breach",
                "duration_ms": pytest.approx(logs[0]["duration_ms"]),
                "engine": "prophet",
                "event": "forecast_fit_completed",
                "input_points": 60,
                "interval": "day",
                "log_level": "info",
                "outcome": "success",
                "output_points": 7,
            }
        ]

    @parameterized.expand(
        [
            ("sunday_start_project", datetime.date(2026, 1, 4)),
            ("monday_start_project", datetime.date(2026, 1, 5)),
        ]
    )
    def test_weekly_forecast_keeps_the_week_start_of_the_history(self, _name, week_start):
        engine = get_forecast_engine({"engine": "prophet"})
        history = 20
        result = engine.forecast(
            _weekly_dates(history, week_start),
            [float(100 + 2 * i) for i in range(history)],
            horizon=4,
            interval_width=0.95,
            interval=IntervalType.WEEK,
        )
        assert [forecast_date[:10] for forecast_date in result.dates] == [
            (week_start + datetime.timedelta(weeks=history + step)).isoformat() for step in range(4)
        ]

    def test_hourly_forecast_skips_a_nonexistent_spring_forward_hour(self):
        engine = get_forecast_engine({"engine": "prophet"})
        history_end = datetime.datetime(2026, 3, 8, 1)
        dates = [(history_end - datetime.timedelta(hours=47 - index)).isoformat() for index in range(48)]

        result = engine.forecast(
            dates,
            [float(100 + index) for index in range(48)],
            horizon=3,
            interval_width=0.95,
            interval=IntervalType.HOUR,
            timezone="America/New_York",
        )

        assert [forecast_date[:19] for forecast_date in result.dates] == [
            "2026-03-08T03:00:00",
            "2026-03-08T04:00:00",
            "2026-03-08T05:00:00",
        ]

    def test_hourly_forecast_accepts_offset_labels_that_span_a_dst_change(self):
        engine = get_forecast_engine({"engine": "prophet"})
        timezone = ZoneInfo("America/New_York")
        start_utc = datetime.datetime(2026, 3, 7, 5, tzinfo=datetime.UTC)
        dates = [(start_utc + datetime.timedelta(hours=index)).astimezone(timezone).isoformat() for index in range(48)]

        result = engine.forecast(
            dates,
            [float(100 + index) for index in range(48)],
            horizon=1,
            interval_width=0.95,
            interval=IntervalType.HOUR,
            timezone="America/New_York",
        )

        assert {date[-6:] for date in dates} == {"-05:00", "-04:00"}
        assert result.dates[0].endswith("-04:00")

    @parameterized.expand(
        [
            ("upward_trend", [float(100 + 2 * i) for i in range(60)], lambda fc: fc.yhat[-1] > 210),
            ("flat", [100.0] * 60, lambda fc: abs(fc.yhat[-1] - 100.0) < 10),
        ]
    )
    def test_forecast_follows_trend(self, _name, values, check):
        engine = get_forecast_engine({"engine": "prophet"})
        result = engine.forecast(_daily_dates(60), values, horizon=7, interval_width=0.95, interval=IntervalType.DAY)
        assert check(result)

    @parameterized.expand(
        [
            ("hourly keeps the hour of day cycle", IntervalType.HOUR, datetime.timedelta(hours=1), 24),
            ("daily keeps the day of week cycle", IntervalType.DAY, datetime.timedelta(days=1), 7),
        ]
    )
    def test_the_minimum_window_is_long_enough_for_the_cycle_of_the_interval(self, _name, interval, step, period):
        engine = get_forecast_engine({"engine": "prophet"})
        history = min_forecast_points(interval)
        start = datetime.datetime(2026, 1, 1)
        dates = [(start + step * index).isoformat() for index in range(history)]
        values = [100 + 40 * math.sin(2 * math.pi * index / period) for index in range(history)]

        result = engine.forecast(dates, values, horizon=period, interval_width=0.95, interval=interval)

        # Prophet reads a seasonality from the elapsed span of the history, not from the point
        # count, so a window one point shorter fits the trend alone and flattens this 80-wide
        # cycle to under 20.
        assert max(result.yhat) - min(result.yhat) > 40

    def test_band_contains_point_forecast(self):
        engine = get_forecast_engine({"engine": "prophet"})
        values = [float(100 + 2 * i + (5 if i % 7 == 0 else 0)) for i in range(60)]
        result = engine.forecast(_daily_dates(60), values, horizon=7, interval_width=0.95, interval=IntervalType.DAY)
        for i in range(7):
            assert result.lower[i] <= result.yhat[i] <= result.upper[i]

    def test_result_exposes_only_future_point_and_context_band(self):
        assert [field.name for field in fields(ForecastResult)] == ["dates", "yhat", "lower", "upper"]

    def test_rejects_unbounded_training_or_output(self):
        engine = get_forecast_engine({"engine": "prophet"})
        with pytest.raises(ForecastConfigurationError, match="1,000"):
            engine.forecast(_daily_dates(1001), [1.0] * 1001, 1, 0.95, IntervalType.DAY)
        with pytest.raises(ForecastConfigurationError, match="250"):
            engine.forecast(_daily_dates(14), [1.0] * 14, 251, 0.95, IntervalType.DAY)

    def test_timeout_is_retryable_and_does_not_change_logger_configuration(self):
        engine = get_forecast_engine({"engine": "prophet", "condition": "target_by_date"})
        cmdstan_logger = logging.getLogger("cmdstanpy")
        prophet_logger = logging.getLogger("prophet")
        before = (cmdstan_logger.disabled, cmdstan_logger.level, prophet_logger.disabled, prophet_logger.level)

        with capture_logs() as logs:
            with patch("prophet.Prophet.fit", side_effect=TimeoutError):
                with pytest.raises(ForecastExecutionError, match="timed out"):
                    engine.forecast(_daily_dates(14), [1.0] * 14, 1, 0.95, IntervalType.DAY)

        after = (cmdstan_logger.disabled, cmdstan_logger.level, prophet_logger.disabled, prophet_logger.level)
        assert after == before
        assert logs[0] == {
            "condition": "target_by_date",
            "duration_ms": pytest.approx(logs[0]["duration_ms"]),
            "engine": "prophet",
            "event": "forecast_fit_completed",
            "input_points": 14,
            "interval": "day",
            "log_level": "warning",
            "outcome": "timeout",
            "output_points": 1,
        }

    def test_total_runtime_limit_is_retryable(self):
        engine = get_forecast_engine({"engine": "prophet", "condition": "future_breach"})
        fake_model = MagicMock()

        with (
            patch("prophet.Prophet", return_value=fake_model),
            patch(
                "products.alerts.backend.forecasting.prophet_engine.time.monotonic",
                side_effect=[0.0, 71.0, 71.0],
            ),
            pytest.raises(ForecastExecutionError, match="timed out"),
        ):
            engine.forecast(_daily_dates(14), [1.0] * 14, 1, 0.95, IntervalType.DAY)

    def test_forecast_leaves_no_cmdstan_output_files_behind(self):
        import cmdstanpy

        def entries() -> set[str]:
            return {
                os.path.join(root, name) for root, dirs, files in os.walk(cmdstanpy._TMPDIR) for name in (*dirs, *files)
            }

        engine = get_forecast_engine({"engine": "prophet"})
        before = entries()
        engine.forecast(_daily_dates(30), [float(100 + i) for i in range(30)], 7, 0.95, IntervalType.DAY)
        assert entries() == before

    def test_forecast_is_deterministic_without_changing_numpy_random_state(self):
        import numpy as np

        engine = get_forecast_engine({"engine": "prophet"})
        values = [float(100 + 2 * i + (-1) ** i * 0.3) for i in range(60)]
        state_before = np.random.get_state()
        first = engine.forecast(_daily_dates(60), values, 7, 0.95, IntervalType.DAY)
        state_after_first = np.random.get_state()
        second = engine.forecast(_daily_dates(60), values, 7, 0.95, IntervalType.DAY)
        state_after_second = np.random.get_state()

        assert first == second
        np.testing.assert_equal(state_before, state_after_first)
        np.testing.assert_equal(state_before, state_after_second)


class TestForecastReach:
    @parameterized.expand(
        [
            ("daily", IntervalType.DAY, datetime.date(2026, 3, 31), 30),
            ("weekly stops before a midweek target", IntervalType.WEEK, datetime.date(2026, 3, 31), 4),
            ("weekly reaches a target on a bucket start", IntervalType.WEEK, datetime.date(2026, 4, 5), 5),
            ("monthly counts calendar months", IntervalType.MONTH, datetime.date(2026, 6, 1), 3),
            ("monthly stops before a mid-month target", IntervalType.MONTH, datetime.date(2026, 5, 20), 2),
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
        with pytest.raises(ValueError, match="within 92 days"):
            horizon_for_target_date(datetime.date(2027, 3, 1), IntervalType.DAY, datetime.date(2026, 3, 1))

    @parameterized.expand(
        [
            ("hourly", IntervalType.HOUR, 7),
            ("daily", IntervalType.DAY, 7),
            ("weekly", IntervalType.WEEK, 7),
            ("monthly clamps to the quarter cap", IntervalType.MONTH, 3),
            ("none_defaults_to_daily", None, 7),
        ]
    )
    def test_an_omitted_horizon_resolves_within_the_reach_cap(self, _name, interval, expected) -> None:
        assert default_horizon(interval) == expected
        validate_forecast_horizon(
            ForecastConfig.model_validate(
                {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach"}
            ),
            interval,
        )

    @parameterized.expand(
        [
            ("30 days is fine", 30, IntervalType.DAY, True),
            ("14 weeks exceeds one quarter", 14, IntervalType.WEEK, False),
            ("4 months exceeds one quarter", 4, IntervalType.MONTH, False),
            ("13 weeks fits", 13, IntervalType.WEEK, True),
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
            ("never below the fit minimum", 1, IntervalType.HOUR, 49),
        ]
    )
    def test_bounded_training_points(self, _name, requested, interval, expected) -> None:
        assert bounded_training_points(requested, interval) == expected

    @parameterized.expand(
        [
            ("daily weekdays only", IntervalType.DAY, DateRange(daysOfWeek=[1, 2, 3, 4, 5]), True),
            ("an unset interval means daily", None, DateRange(daysOfWeek=[6, 7]), True),
            ("daily with every day selected", IntervalType.DAY, DateRange(daysOfWeek=[1, 2, 3, 4, 5, 6, 7]), False),
            ("daily with no day filter", IntervalType.DAY, DateRange(), False),
            ("daily with no date range", IntervalType.DAY, None, False),
            ("weekly keeps every bucket", IntervalType.WEEK, DateRange(daysOfWeek=[1, 2, 3, 4, 5]), False),
            ("hourly keeps every bucket", IntervalType.HOUR, DateRange(daysOfWeek=[1, 2, 3, 4, 5]), False),
        ]
    )
    def test_validate_forecast_days_of_week(self, _name, interval, date_range, rejected) -> None:
        if not rejected:
            validate_forecast_days_of_week(date_range, interval)
            return
        with pytest.raises(ValueError, match="excludes days of the week"):
            validate_forecast_days_of_week(date_range, interval)

    def test_no_interval_scans_more_than_two_years(self) -> None:
        for interval in (IntervalType.HOUR, IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH):
            points = bounded_training_points(1_000_000, interval)
            assert forecast_reach_days(points, interval) <= MAX_FORECAST_LOOKBACK_DAYS

    @parameterized.expand(
        [
            ("daily", IntervalType.DAY, 1),
            ("weekly", IntervalType.WEEK, 7),
            ("monthly", IntervalType.MONTH, 28),
        ]
    )
    def test_stale_data_can_exceed_the_save_time_reach(self, _name, interval, bucket_age_days) -> None:
        today = datetime.date(2026, 3, 1)
        furthest_saveable = today + datetime.timedelta(days=MAX_FORECAST_REACH_DAYS)
        horizon_for_target_date(furthest_saveable, interval, today)

        last_bucket = today - datetime.timedelta(days=bucket_age_days)
        assert (furthest_saveable - last_bucket).days > MAX_FORECAST_REACH_DAYS
