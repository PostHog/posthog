import time
import logging
import threading

import structlog

from posthog.schema import IntervalType

from products.alerts.backend.forecasting.engine import SUPPORTED_FORECAST_INTERVALS, ForecastResult

# cmdstanpy reattaches its own stderr handler during optimize(), so setLevel alone does not hold.
# Disabling the logger outright is what actually keeps per-fit chain logs out of the worker output.
logging.getLogger("cmdstanpy").disabled = True
logging.getLogger("prophet").setLevel(logging.WARNING)

logger = structlog.get_logger(__name__)

# Prophet draws its uncertainty interval through numpy's global RNG, so two identical fits return
# different band edges: measured at 3.7% of band width, with fit_coverage swinging 0.95 to 1.00.
# That is enough to flip a band_deviation firing decision and a fit-quality verdict between checks.
# An alert has to decide the same way twice on the same data, so the draw is pinned. The global
# state is restored afterwards, because it belongs to the worker rather than to this fit.
_UNCERTAINTY_SEED = 20260818

# Seeding a global is only deterministic if one fit owns it at a time. evaluate_alert runs under
# thread_sensitive=False, so a worker fits several alerts concurrently: without this lock two fits
# interleave their seed and restore, neither is reproducible, and the worker is left permanently
# seeded. The lock is correctness, not throughput tuning.
_FIT_LOCK = threading.Lock()

_FREQ: dict[IntervalType, str] = {
    IntervalType.HOUR: "h",
    IntervalType.DAY: "D",
    IntervalType.WEEK: "W",
    IntervalType.MONTH: "MS",
}

# Validation rejects anything outside this set, so a missing key here would be a silent daily fit.
# Raised rather than asserted because python -O strips asserts, and this invariant is load-bearing.
if set(_FREQ) != set(SUPPORTED_FORECAST_INTERVALS):
    raise RuntimeError(f"Prophet frequency map {set(_FREQ)} does not match {set(SUPPORTED_FORECAST_INTERVALS)}")


class ProphetEngine:
    def forecast(
        self,
        dates: list[str],
        values: list[float],
        horizon: int,
        interval_width: float,
        interval: IntervalType | None,
        include_history: bool = False,
    ) -> ForecastResult:
        import numpy as np  # noqa: PLC0415 — keeps the heavy dep off the django.setup() path
        import pandas as pd  # noqa: PLC0415 — keeps the heavy dep off the django.setup() path
        from prophet import Prophet  # noqa: PLC0415 — keeps the heavy dep off the django.setup() path

        df = pd.DataFrame({"ds": pd.to_datetime(dates), "y": values})
        # mcmc_samples=0 pins the deterministic MAP fit; seasonalities stay on Prophet's auto-detection.
        model = Prophet(interval_width=interval_width, mcmc_samples=0)

        start = time.monotonic()
        with _FIT_LOCK:
            rng_state = np.random.get_state()
            try:
                np.random.seed(_UNCERTAINTY_SEED)
                model.fit(df)
                freq = _FREQ.get(interval or IntervalType.DAY, "D")
                future = model.make_future_dataframe(periods=horizon, freq=freq, include_history=include_history)
                prediction = model.predict(future)
            finally:
                np.random.set_state(rng_state)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "forecast_fit_completed", engine="prophet", horizon=horizon, n_points=len(values), duration_ms=duration_ms
        )

        # Without history rows the frame is the horizon alone, so there is nothing to split off.
        history = prediction.iloc[: len(values)] if include_history else None
        forecast = prediction.iloc[len(values) :] if include_history else prediction

        fit_mape: float | None = None
        fit_coverage: float | None = None
        history_lower: list[float] | None = None
        history_upper: list[float] | None = None
        if history is not None:
            # How far off the fitted values are, and whether the band's observed coverage matches the
            # requested interval_width. The simulate UI turns these into a verdict and a band.
            actuals = df["y"].to_numpy()
            fitted = history["yhat"].to_numpy()
            nonzero = actuals != 0
            fit_mape = (
                float(abs((actuals[nonzero] - fitted[nonzero]) / actuals[nonzero]).mean()) if nonzero.any() else None
            )
            lower_bounds, upper_bounds = history["yhat_lower"].to_numpy(), history["yhat_upper"].to_numpy()
            fit_coverage = float(((actuals >= lower_bounds) & (actuals <= upper_bounds)).mean())
            history_lower = [float(v) for v in lower_bounds]
            history_upper = [float(v) for v in upper_bounds]

        components = {
            name: [float(v) for v in forecast[name]] for name in ("trend", "weekly", "yearly") if name in forecast
        }
        return ForecastResult(
            dates=[ts.isoformat() for ts in forecast["ds"]],
            yhat=[float(v) for v in forecast["yhat"]],
            lower=[float(v) for v in forecast["yhat_lower"]],
            upper=[float(v) for v in forecast["yhat_upper"]],
            components=components or None,
            fit_mape=fit_mape,
            fit_coverage=fit_coverage,
            history_lower=history_lower,
            history_upper=history_upper,
        )
