import logging

from posthog.schema import IntervalType

from products.alerts.backend.forecasting.engine import ForecastResult

# cmdstanpy INFO logs on every fit are pure noise at alert-check volume.
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)

_FREQ: dict[IntervalType, str] = {
    IntervalType.HOUR: "h",
    IntervalType.DAY: "D",
    IntervalType.WEEK: "W",
    IntervalType.MONTH: "MS",
}


class ProphetEngine:
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

        df = pd.DataFrame({"ds": pd.to_datetime(dates), "y": values})
        # mcmc_samples=0 pins the deterministic MAP fit; seasonalities stay on Prophet's auto-detection.
        model = Prophet(interval_width=interval_width, mcmc_samples=0)
        model.fit(df)
        freq = _FREQ.get(interval or IntervalType.DAY, "D")
        future = model.make_future_dataframe(periods=horizon, freq=freq, include_history=True)
        prediction = model.predict(future)
        history, forecast = prediction.iloc[: len(values)], prediction.iloc[len(values) :]

        # In-sample fit quality: how far off the fitted values are, and whether the band's observed
        # coverage matches the requested interval_width — the simulate UI turns these into a verdict.
        actuals = df["y"].to_numpy()
        fitted = history["yhat"].to_numpy()
        nonzero = actuals != 0
        fit_mape = float(abs((actuals[nonzero] - fitted[nonzero]) / actuals[nonzero]).mean()) if nonzero.any() else None
        inside = (actuals >= history["yhat_lower"].to_numpy()) & (actuals <= history["yhat_upper"].to_numpy())
        fit_coverage = float(inside.mean())

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
        )
