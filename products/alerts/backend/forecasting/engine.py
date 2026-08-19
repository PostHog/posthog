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

# In band half-widths past the edge. A 0.95 band is about two standard deviations wide, so a
# threshold of 2 sits near six of them and stops firing on anything. The ceiling leaves room to
# express "only when it is far out" without letting a save pass that can never fire.
MAX_SCORE_THRESHOLD = 3.0

# A duration rather than a count of intervals. 30 intervals means 30 days on a daily insight and
# 30 months on a monthly one, so the same number expresses very different confidence.
MAX_FORECAST_REACH_DAYS = 183

_INTERVAL_DAYS: dict[IntervalType, float] = {
    IntervalType.HOUR: 1 / 24,
    IntervalType.DAY: 1,
    IntervalType.WEEK: 7,
    IntervalType.MONTH: 30.4,
}

# Two ceilings on the training window, because it blows up in two independent ways. A point count
# bounds the fit: Prophet draws 1000 uncertainty samples per predicted row, so 17k rows is not a
# slower fit, it is a different order of cost. A duration bounds the query: 90 points is three days
# of hourly data and seven and a half years of monthly data.
MAX_FORECAST_TRAINING_POINTS = 1000
MAX_FORECAST_LOOKBACK_DAYS = 730


# Intervals an engine can map to a series frequency. An unmapped interval would fit at the wrong
# cadence, and because the lookback is a point count it would also widen the query by that unit:
# 90 quarters is 22 years of events per check.
SUPPORTED_FORECAST_INTERVALS = frozenset({IntervalType.HOUR, IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH})


def bounded_training_points(requested: int, interval: IntervalType | None) -> int:
    """Clamp a requested training window so no scheduled check can scan years of events or fit tens
    of thousands of rows. Never returns fewer points than the interval needs to fit at all."""
    per_interval = _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)
    by_duration = int(MAX_FORECAST_LOOKBACK_DAYS / per_interval)
    return max(min_forecast_points(interval), min(requested, MAX_FORECAST_TRAINING_POINTS, by_duration))


def forecast_reach_days(horizon: int, interval: IntervalType | None) -> float:
    """How far ahead an interval-count horizon actually reaches. Named for the unit so a caller
    cannot read a count of intervals as a number of days."""
    return horizon * _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)


def horizon_for_target_date(target_date: date, interval: IntervalType | None, today: date) -> int:
    """Save-time check: how far ahead a target date asks the forecast to reach, measured from today.

    Only the save path enforces the reach cap. Evaluation derives its own horizon from the last
    completed bucket and never re-checks the cap, because the two anchors cannot be kept in step:
    a calendar-aligned bucket start sits a varying distance from today, so any constant offset is
    right on one day of the cycle and wrong on the rest.
    """
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
    """Whole intervals from start to end, at least one. No cap: the caller decides what is too far."""
    days = (end - start).days
    return max(1, ceil(days / _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1)))


def max_evaluable_horizon(interval: IntervalType | None) -> int:
    """Ceiling on predicted points at evaluation. A healthy insight needs the reach cap plus a
    bucket; anything beyond twice that means the insight stopped receiving data, not that the
    target is unreasonable."""
    return ceil(2 * MAX_FORECAST_REACH_DAYS / _INTERVAL_DAYS.get(interval or IntervalType.DAY, 1))


def validate_forecast_horizon_and_width(
    parsed: ForecastConfig, interval: IntervalType | None = None, *, check_horizon: bool = True
) -> None:
    """Shared by the save path and the simulate_forecast endpoint so their bounds can't drift.

    The horizon is a count of intervals, so how far it reaches depends on the insight. Callers that
    know the interval should pass it; without one the check assumes daily.
    """
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
