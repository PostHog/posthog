from datetime import date
from math import ceil
from typing import Protocol

from posthog.schema import ForecastConfig, IntervalType

from posthog.dataclasses import frozen

# Codegen collapses the single-member ForecastEngineType TS enum into an inline Literal["prophet"]
# on ForecastConfig.engine, so no Python symbol exists to import — hence a local constant. When a
# second engine lands, the enum stops collapsing and this becomes an import.
PROPHET_ENGINE = "prophet"

FORECAST_LOOKBACK_POINTS = 90
DEFAULT_HORIZON = 7
DEFAULT_INTERVAL_WIDTH = 0.95

# A duration rather than a count of intervals. 30 intervals means 30 days on a daily insight and
# 30 months on a monthly one, so the same number expresses very different confidence.
MAX_FORECAST_REACH_DAYS = 183

_INTERVAL_DAYS: dict[IntervalType, float] = {
    IntervalType.HOUR: 1 / 24,
    IntervalType.DAY: 1,
    IntervalType.WEEK: 7,
    IntervalType.MONTH: 30.4,
}

# Intervals an engine can map to a series frequency. An unmapped interval would fit at the wrong
# cadence, and because the lookback is a point count it would also widen the query by that unit:
# 90 quarters is 22 years of events per check.
SUPPORTED_FORECAST_INTERVALS = frozenset({IntervalType.HOUR, IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH})


def forecast_reach_days(horizon: int, interval: IntervalType | None) -> float:
    """How far ahead an interval-count horizon actually reaches. Named for the unit so a caller
    cannot read a count of intervals as a number of days."""
    return horizon * _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)


def horizon_for_target_date(target_date: date, interval: IntervalType | None, today: date) -> int:
    """Intervals between today and the target date, for a forecast that must reach a fixed date."""
    days = (target_date - today).days
    if days <= 0:
        raise ValueError("The target date must be in the future.")
    if days > MAX_FORECAST_REACH_DAYS:
        raise ValueError(
            "A forecast target must be within 6 months. Move the date closer, or use an insight "
            "with a coarser interval."
        )
    return max(1, ceil(days / _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)))


def validate_forecast_horizon_and_width(parsed: ForecastConfig, interval: IntervalType | None = None) -> None:
    """Shared by the save path and the simulate_forecast endpoint so their bounds can't drift.

    The horizon is a count of intervals, so how far it reaches depends on the insight. Callers that
    know the interval should pass it; without one the check assumes daily.
    """
    if parsed.horizon is not None:
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
    """Shared by the save path and the simulate_forecast endpoint. A None interval means the insight
    uses the daily default, which is supported."""
    if interval is not None and interval not in SUPPORTED_FORECAST_INTERVALS:
        raise ValueError(
            "Forecast alerts support hourly, daily, weekly, and monthly insights. "
            "Change the insight's interval to one of these."
        )


def min_forecast_points(interval: IntervalType | None) -> int:
    """Roughly two seasonal cycles: hourly series need two days of points to see a daily cycle;
    everything else needs two weeks of points to see a weekly cycle."""
    return 48 if interval == IntervalType.HOUR else 14


@frozen
class ForecastResult:
    """One point per future interval, chronologically ascending; lists share length == horizon."""

    dates: list[str]
    yhat: list[float]
    lower: list[float]
    upper: list[float]
    # Optional interpretability/quality extras — engines without them (a future Chronos) leave None.
    components: dict[str, list[float]] | None = None  # keys: trend/weekly/yearly, per horizon point
    # The remaining fields describe the training window, so they are only populated when the caller
    # asks for in-sample output. Scheduled checks don't, because nothing on that path reads them.
    fit_mape: float | None = None  # in-sample mean absolute percentage error
    fit_coverage: float | None = None  # share of training points inside the prediction interval
    history_lower: list[float] | None = None  # one per training point, aligned with the input dates
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
    """Resolve the engine named in the config, mirroring detectors.get_detector. The import is lazy
    so Prophet (a heavy dep) loads only in processes that actually forecast."""
    engine = forecast_config.get("engine", PROPHET_ENGINE)
    if engine == PROPHET_ENGINE:
        from products.alerts.backend.forecasting.prophet_engine import (  # noqa: PLC0415 — keeps the heavy dep off the django.setup() path
            ProphetEngine,
        )

        return ProphetEngine()
    raise ValueError(f"Unknown forecast engine: {engine}")
