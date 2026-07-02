from dataclasses import dataclass
from typing import Protocol

from posthog.schema import IntervalType

# Codegen collapses the single-member ForecastEngineType TS enum into an inline Literal["prophet"]
# on ForecastConfig.engine, so no Python symbol exists to import — hence a local constant. When a
# second engine lands, the enum stops collapsing and this becomes an import.
PROPHET_ENGINE = "prophet"

FORECAST_LOOKBACK_POINTS = 90
DEFAULT_HORIZON = 7
MAX_FORECAST_HORIZON = 30
DEFAULT_INTERVAL_WIDTH = 0.95


def min_forecast_points(interval: IntervalType | None) -> int:
    """Roughly two seasonal cycles: hourly series need two days of points to see a daily cycle;
    everything else needs two weeks of points to see a weekly cycle."""
    return 48 if interval == IntervalType.HOUR else 14


@dataclass
class ForecastResult:
    """One point per future interval, chronologically ascending; lists share length == horizon."""

    dates: list[str]
    yhat: list[float]
    lower: list[float]
    upper: list[float]
    # Optional interpretability/quality extras — engines without them (a future Chronos) leave None.
    components: dict[str, list[float]] | None = None  # keys: trend/weekly/yearly, per horizon point
    fit_mape: float | None = None  # in-sample mean absolute percentage error
    fit_coverage: float | None = None  # share of training points inside the prediction interval


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
    """Resolve the engine named in the config, mirroring detectors.get_detector. The import is lazy
    so Prophet (a heavy dep) loads only in processes that actually forecast."""
    engine = forecast_config.get("engine", PROPHET_ENGINE)
    if engine == PROPHET_ENGINE:
        from products.alerts.backend.forecasting.prophet_engine import (  # noqa: PLC0415 — keeps the heavy dep off the django.setup() path
            ProphetEngine,
        )

        return ProphetEngine()
    raise ValueError(f"Unknown forecast engine: {engine}")
