from datetime import date
from math import ceil
from typing import Protocol

from posthog.schema import ForecastConfig, IntervalType

from posthog.dataclasses import frozen

PROPHET_ENGINE = "prophet"

FORECAST_LOOKBACK_POINTS = 90
DEFAULT_HORIZON = 7
DEFAULT_INTERVAL_WIDTH = 0.95

MAX_SCORE_THRESHOLD = 3.0

MAX_FORECAST_REACH_DAYS = 183

_INTERVAL_DAYS: dict[IntervalType, float] = {
    IntervalType.HOUR: 1 / 24,
    IntervalType.DAY: 1,
    IntervalType.WEEK: 7,
    IntervalType.MONTH: 30.4,
}

MAX_FORECAST_TRAINING_POINTS = 1000
MAX_FORECAST_LOOKBACK_DAYS = 730


SUPPORTED_FORECAST_INTERVALS = frozenset({IntervalType.HOUR, IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH})


def bounded_training_points(requested: int, interval: IntervalType | None) -> int:
    per_interval = _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)
    by_duration = int(MAX_FORECAST_LOOKBACK_DAYS / per_interval)
    return max(min_forecast_points(interval), min(requested, MAX_FORECAST_TRAINING_POINTS, by_duration))


def forecast_reach_days(horizon: int, interval: IntervalType | None) -> float:
    return horizon * _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)


def horizon_for_target_date(target_date: date, interval: IntervalType | None, today: date) -> int:
    days = (target_date - today).days
    if days <= 0:
        raise ValueError("The target date must be in the future.")
    if days > MAX_FORECAST_REACH_DAYS:
        raise ValueError(
            "A forecast target must be within 6 months. Move the date closer, or use an insight "
            "with a coarser interval."
        )
    return intervals_between(today, target_date, interval)


def intervals_between(start: date, end: date, interval: IntervalType | None) -> int:
    days = (end - start).days
    return max(1, ceil(days / _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)))


def max_evaluable_horizon(interval: IntervalType | None) -> int:
    return ceil(2 * MAX_FORECAST_REACH_DAYS / _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1))


def validate_forecast_horizon_and_width(
    parsed: ForecastConfig, interval: IntervalType | None = None, *, check_horizon: bool = True
) -> None:
    if check_horizon and parsed.horizon is not None:
        if parsed.horizon < 1:
            raise ValueError("Forecast horizon must be at least 1 interval")
        if forecast_reach_days(parsed.horizon, interval) > MAX_FORECAST_REACH_DAYS:
            raise ValueError(
                "A forecast can look ahead at most 6 months. Lower the horizon, or use an insight "
                "with a shorter interval."
            )
    if parsed.interval_width is not None and not (0 < parsed.interval_width < 1):
        raise ValueError("Forecast interval_width must be between 0 and 1 (e.g. 0.8 or 0.95)")


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
    components: dict[str, list[float]] | None = None
    fit_mape: float | None = None
    fit_coverage: float | None = None
    history_lower: list[float] | None = None
    history_upper: list[float] | None = None


class ForecastEngine(Protocol):
    def forecast(
        self,
        dates: list[str],
        values: list[float],
        horizon: int,
        interval_width: float,
        interval: IntervalType | None,
        include_history: bool = False,
    ) -> ForecastResult: ...


def get_forecast_engine(forecast_config: dict) -> ForecastEngine:
    engine = forecast_config.get("engine", PROPHET_ENGINE)
    if engine == PROPHET_ENGINE:
        from products.alerts.backend.forecasting.prophet_engine import (  # noqa: PLC0415 — keeps the heavy dep off the django.setup() path
            ProphetEngine,
        )

        return ProphetEngine()
    raise ValueError(f"Unknown forecast engine: {engine}")
