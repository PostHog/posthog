import math
import time
import tempfile
import statistics
from statistics import NormalDist

import structlog

from posthog.schema import IntervalType

from products.alerts.backend.forecasting.engine import (
    FORECAST_FIT_TIMEOUT_SECONDS,
    FORECAST_TOTAL_TIMEOUT_SECONDS,
    MAX_FORECAST_OUTPUT_POINTS,
    MAX_FORECAST_TRAINING_POINTS,
    SUPPORTED_FORECAST_INTERVALS,
    ForecastConfigurationError,
    ForecastExecutionError,
    ForecastResult,
)

logger = structlog.get_logger(__name__)

_FREQ: dict[IntervalType, str] = {
    IntervalType.HOUR: "h",
    IntervalType.DAY: "D",
    # A fixed 7-day step keeps the week start that the history dates already carry. The pandas "W"
    # alias re-anchors every future point to a Sunday, which misses the buckets of a Monday-start project.
    IntervalType.WEEK: "7D",
    IntervalType.MONTH: "MS",
}

if set(_FREQ) != set(SUPPORTED_FORECAST_INTERVALS):
    raise RuntimeError(f"Prophet frequency map {set(_FREQ)} does not match {set(SUPPORTED_FORECAST_INTERVALS)}")


class ProphetEngine:
    def __init__(self, *, condition: str):
        self._condition = condition

    def _log_outcome(
        self,
        outcome: str,
        start: float,
        interval: IntervalType | None,
        input_points: int,
        output_points: int,
    ) -> float:
        duration_ms = (time.monotonic() - start) * 1000
        log = logger.info if outcome == "success" else logger.warning
        log(
            "forecast_fit_completed",
            engine="prophet",
            condition=self._condition,
            interval=(interval or IntervalType.DAY).value,
            input_points=input_points,
            output_points=output_points,
            duration_ms=duration_ms,
            outcome=outcome,
        )
        return duration_ms

    def forecast(
        self,
        dates: list[str],
        values: list[float],
        horizon: int,
        interval_width: float,
        interval: IntervalType | None,
    ) -> ForecastResult:
        import pandas as pd  # noqa: PLC0415 — keeps the heavy dep off the django.setup() path
        from prophet import Prophet  # noqa: PLC0415 — keeps the heavy dep off the django.setup() path

        if len(dates) != len(values):
            raise ForecastConfigurationError("Forecast dates and values must have the same length.")
        if len(values) > MAX_FORECAST_TRAINING_POINTS:
            raise ForecastConfigurationError(
                f"A forecast can use at most {MAX_FORECAST_TRAINING_POINTS:,} training points."
            )
        if horizon < 1 or horizon > MAX_FORECAST_OUTPUT_POINTS:
            raise ForecastConfigurationError(
                f"A forecast must return between 1 and {MAX_FORECAST_OUTPUT_POINTS} future points."
            )
        if interval is not None and interval not in SUPPORTED_FORECAST_INTERVALS:
            raise ForecastConfigurationError("Forecast interval is not supported.")
        if not 0 < interval_width < 1:
            raise ForecastConfigurationError("Forecast interval width must be between 0 and 1.")

        df = pd.DataFrame({"ds": pd.to_datetime(dates), "y": values})
        model = Prophet(interval_width=interval_width, mcmc_samples=0, uncertainty_samples=0)

        start = time.monotonic()
        try:
            # CmdStanPy writes each fit's CSV and stdout into a per-run directory and removes it
            # only when the process exits. Scheduled evaluations and previews both run in
            # long-lived workers, so an unset output_dir makes those files collect for the life of
            # the process. The directory must stay until predict returns.
            with tempfile.TemporaryDirectory(prefix="prophet_fit_") as fit_output_dir:
                model.fit(df, timeout=FORECAST_FIT_TIMEOUT_SECONDS, output_dir=fit_output_dir)
                freq = _FREQ.get(interval or IntervalType.DAY, "D")
                future = model.make_future_dataframe(periods=horizon, freq=freq, include_history=True)
                prediction = model.predict(future)
        except TimeoutError as error:
            self._log_outcome("timeout", start, interval, len(values), horizon)
            raise ForecastExecutionError("Forecast model execution timed out.") from error
        except Exception as error:
            self._log_outcome("failed", start, interval, len(values), horizon)
            raise ForecastExecutionError("Forecast model execution failed.") from error

        duration_ms = (time.monotonic() - start) * 1000
        if duration_ms > FORECAST_TOTAL_TIMEOUT_SECONDS * 1000:
            self._log_outcome("timeout", start, interval, len(values), horizon)
            raise ForecastExecutionError("Forecast model execution timed out.")
        self._log_outcome("success", start, interval, len(values), horizon)

        history = prediction.iloc[: len(values)]
        forecast = prediction.iloc[len(values) :]
        # Prophet's uncertainty sampler mutates NumPy's process-global RNG. Keep it disabled and
        # derive an explicitly contextual (not calibrated) preview band from fitted residuals.
        residuals = [actual - float(fitted) for actual, fitted in zip(values, history["yhat"], strict=True)]
        residual_stddev = statistics.stdev(residuals) if len(residuals) > 1 else 0.0
        z_score = NormalDist().inv_cdf((1 + interval_width) / 2)
        margins = [z_score * residual_stddev * math.sqrt(1 + step / len(values)) for step in range(1, horizon + 1)]
        point_forecast = [float(value) for value in forecast["yhat"]]
        return ForecastResult(
            dates=[ts.isoformat() for ts in forecast["ds"]],
            yhat=point_forecast,
            lower=[value - margin for value, margin in zip(point_forecast, margins, strict=True)],
            upper=[value + margin for value, margin in zip(point_forecast, margins, strict=True)],
        )
