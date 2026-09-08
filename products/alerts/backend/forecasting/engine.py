from datetime import date
from math import ceil, floor
from typing import Protocol

from posthog.schema import DateRange, ForecastConfig, FutureBreachForecastConfig, IntervalType

from posthog.dataclasses import frozen

PROPHET_ENGINE = "prophet"

DEFAULT_HORIZON = 7
DEFAULT_INTERVAL_WIDTH = 0.95

MAX_FORECAST_REACH_DAYS = 92
MAX_FORECAST_OUTPUT_POINTS = 250

_INTERVAL_DAYS: dict[IntervalType, float] = {
    IntervalType.HOUR: 1 / 24,
    IntervalType.DAY: 1,
    IntervalType.WEEK: 7,
    IntervalType.MONTH: 30.4,
}

MAX_FORECAST_TRAINING_POINTS = 1000
MAX_FORECAST_LOOKBACK_DAYS = 730
FORECAST_FIT_TIMEOUT_SECONDS = 60
FORECAST_TOTAL_TIMEOUT_SECONDS = 70


SUPPORTED_FORECAST_INTERVALS = frozenset({IntervalType.HOUR, IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH})


def bounded_training_points(requested: int, interval: IntervalType | None) -> int:
    per_interval = _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)
    by_duration = int(MAX_FORECAST_LOOKBACK_DAYS / per_interval)
    return max(min_forecast_points(interval), min(requested, MAX_FORECAST_TRAINING_POINTS, by_duration))


def bounded_lookback_days(interval: IntervalType | None) -> int:
    """Days of history a forecast can use, so a query does not scan what the fit then discards.

    Mirrors bounded_training_points, which caps by duration and by training points. The two caps
    agree for day, week, and month intervals. Only an hourly interval is bound by the point cap,
    at about six weeks. Rounds up, so the range still covers every point the fit keeps.
    """
    per_interval = _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)
    return min(MAX_FORECAST_LOOKBACK_DAYS, ceil(MAX_FORECAST_TRAINING_POINTS * per_interval))


def forecast_reach_days(horizon: int, interval: IntervalType | None) -> float:
    return horizon * _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)


def horizon_for_target_date(target_date: date, interval: IntervalType | None, today: date) -> int:
    days = (target_date - today).days
    if days <= 0:
        raise ValueError("The target date must be in the future.")
    if days > MAX_FORECAST_REACH_DAYS:
        raise ValueError(
            "A forecast target must be within 92 days. Move the date closer, or use an insight with a coarser interval."
        )
    horizon = intervals_between(today, target_date, interval)
    if horizon > MAX_FORECAST_OUTPUT_POINTS:
        raise ValueError(
            f"A forecast can return at most {MAX_FORECAST_OUTPUT_POINTS} future points. "
            "Use a coarser insight interval for this target date."
        )
    return horizon


def intervals_between(start: date, end: date, interval: IntervalType | None) -> int:
    days = (end - start).days
    return max(1, ceil(days / _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)))


def max_evaluable_horizon(interval: IntervalType | None) -> int:
    # Rounds down because validate_forecast_horizon rejects a horizon whose reach passes the
    # 92-day cap. Rounding up would return a horizon that cannot be saved.
    return min(
        MAX_FORECAST_OUTPUT_POINTS,
        floor(MAX_FORECAST_REACH_DAYS / _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)),
    )


def default_horizon(interval: IntervalType | None) -> int:
    return min(DEFAULT_HORIZON, max_evaluable_horizon(interval))


def validate_forecast_horizon(
    parsed: ForecastConfig, interval: IntervalType | None = None, *, check_horizon: bool = True
) -> None:
    config = parsed.root
    if check_horizon and isinstance(config, FutureBreachForecastConfig):
        horizon = config.horizon if config.horizon is not None else default_horizon(interval)
        if horizon < 1:
            raise ValueError("Forecast horizon must be at least 1 interval")
        if horizon > MAX_FORECAST_OUTPUT_POINTS:
            raise ValueError(f"A forecast can return at most {MAX_FORECAST_OUTPUT_POINTS} future points.")
        if forecast_reach_days(horizon, interval) > MAX_FORECAST_REACH_DAYS:
            raise ValueError(
                "A forecast can look ahead at most 92 days. Lower the horizon, or use an insight "
                "with a shorter interval."
            )


def validate_forecast_days_of_week(date_range: DateRange | None, interval: IntervalType | None) -> None:
    """Reject a daily insight that leaves days out of its date axis.

    The trends runner drops the deselected buckets at a day interval, so the history arrives with
    gaps. The forecast steps one calendar day at a time and fills those gaps back in, using a weekly
    shape the history never constrained, which returns values for days the insight does not chart.
    Longer intervals keep every bucket, so they stay supported.
    """
    if interval not in (None, IntervalType.DAY):
        return
    days_of_week = date_range.daysOfWeek if date_range else None
    if days_of_week and len(set(days_of_week)) < 7:
        raise ValueError(
            "Forecast alerts don't support a daily insight that excludes days of the week. "
            "Include all days, or switch the insight to a weekly interval."
        )


def validate_forecast_interval(interval: IntervalType | None) -> None:
    if interval is not None and interval not in SUPPORTED_FORECAST_INTERVALS:
        raise ValueError(
            "Forecast alerts support hourly, daily, weekly, and monthly insights. "
            "Change the insight's interval to one of these."
        )


def min_forecast_points(interval: IntervalType | None) -> int:
    return 48 if interval == IntervalType.HOUR else 14


@frozen
class ForecastResult:
    dates: list[str]
    yhat: list[float]
    lower: list[float]
    upper: list[float]


class ForecastConfigurationError(ValueError):
    pass


class ForecastExecutionError(RuntimeError):
    pass


class ForecastEngine(Protocol):
    def forecast(
        self,
        dates: list[str],
        values: list[float],
        horizon: int,
        interval_width: float,
        interval: IntervalType | None,
    ) -> ForecastResult: ...


def get_forecast_engine(forecast_config: dict) -> ForecastEngine:
    engine = forecast_config.get("engine", PROPHET_ENGINE)
    if engine == PROPHET_ENGINE:
        from products.alerts.backend.forecasting.prophet_engine import (  # noqa: PLC0415 — keeps the heavy dep off the django.setup() path
            ProphetEngine,
        )

        return ProphetEngine(condition=str(forecast_config.get("condition") or "unknown"))
    raise ForecastConfigurationError(f"Unknown forecast engine: {engine}")
