from typing import Any, Optional

from posthog.schema import InsightThreshold, IntervalType, TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team import Team
from posthog.models.user import User
from posthog.schema_enums import ForecastConditionType
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, AlertEvaluationResult
from posthog.utils import get_from_dict_or_attr

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ExtractionResult,
    SimulationContext,
    execution_mode_for_alert,
)
from products.alerts.backend.evaluation.detector import extract_trends_series
from products.alerts.backend.forecasting.engine import (
    DEFAULT_HORIZON,
    DEFAULT_INTERVAL_WIDTH,
    FORECAST_LOOKBACK_POINTS,
    ForecastResult,
    get_forecast_engine,
    min_forecast_points,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


def _forecast_min_samples(forecast_config: dict[str, Any]) -> int:
    # Fetch a wide window: enough history for seasonality plus the horizon we predict past it.
    horizon = int(forecast_config.get("horizon") or DEFAULT_HORIZON)
    return max(FORECAST_LOOKBACK_POINTS, 4 * horizon) + 1


def _clean_points(result: ExtractionResult) -> tuple[list[str], list[float]]:
    s = result.series[0]
    dates: list[str] = []
    values: list[float] = []
    for p in s.points:
        if p.date is not None and p.value is not None:
            dates.append(p.date)
            values.append(p.value)
    return dates, values


def _decomposition_suffix(forecast: ForecastResult, index: int) -> str:
    """Render the forecast decomposition for one point, e.g. " (trend 1210.00, weekly seasonality −12%)".
    Empty when the engine produced no components — the message degrades to expected-vs-actual."""
    if not forecast.components:
        return ""
    trend_series = forecast.components.get("trend")
    trend = trend_series[index] if trend_series and index < len(trend_series) else None
    parts: list[str] = []
    if trend is not None:
        parts.append(f"trend {trend:.2f}")
    for name in ("weekly", "yearly"):
        series = forecast.components.get(name)
        if series and index < len(series) and trend:
            parts.append(f"{name} seasonality {series[index] / trend:+.0%}")
    return f" ({', '.join(parts)})" if parts else ""


def _evaluate_band_deviation(
    dates: list[str],
    values: list[float],
    label: str,
    engine: Any,
    interval_width: float,
    interval_type: IntervalType | None,
    interval_value: str | None,
) -> AlertEvaluationResult:
    """Fit on history excluding the latest completed point, predict one interval, fire if that
    actual point sits outside the band."""
    forecast = engine.forecast(dates[:-1], values[:-1], 1, interval_width, interval_type)
    actual = values[-1]
    lower, upper = forecast.lower[0], forecast.upper[0]
    breaches: list[str] = []
    if actual < lower or actual > upper:
        breaches = [
            f"The latest value for {label} ({actual:.2f}) is outside the expected range "
            f"({lower:.2f} to {upper:.2f}){_decomposition_suffix(forecast, 0)}"
        ]
    return AlertEvaluationResult(
        value=actual,
        breaches=breaches,
        interval=interval_value,
        triggered_metadata={"forecast": {"lower": lower, "upper": upper, "yhat": forecast.yhat[0]}}
        if breaches
        else None,
    )


def _evaluate_future_breach(
    dates: list[str],
    values: list[float],
    label: str,
    forecast_config: dict[str, Any],
    engine: Any,
    interval_width: float,
    interval_type: IntervalType | None,
    threshold: InsightThreshold | None,
    interval_value: str | None,
) -> AlertEvaluationResult:
    """Fit on the full history, predict `horizon` intervals, fire if the point forecast crosses
    the threshold bounds."""
    horizon = int(forecast_config.get("horizon") or DEFAULT_HORIZON)
    forecast = engine.forecast(dates, values, horizon, interval_width, interval_type)
    bounds = threshold.bounds if threshold else None
    if bounds is None or (bounds.lower is None and bounds.upper is None):
        return AlertEvaluationResult(value=values[-1], breaches=[], interval=interval_value)

    for i, predicted in enumerate(forecast.yhat):
        breach_date = forecast.dates[i][:10]
        if bounds.upper is not None and predicted > bounds.upper:
            message = (
                f"Forecast for {label}: predicted value {predicted:.2f} on {breach_date} "
                f"is more than the upper threshold ({bounds.upper}){_decomposition_suffix(forecast, i)}"
            )
        elif bounds.lower is not None and predicted < bounds.lower:
            message = (
                f"Forecast for {label}: predicted value {predicted:.2f} on {breach_date} "
                f"is less than the lower threshold ({bounds.lower}){_decomposition_suffix(forecast, i)}"
            )
        else:
            continue
        return AlertEvaluationResult(
            value=predicted,
            breaches=[message],
            interval=interval_value,
            triggered_metadata={
                "forecast": {
                    "breach_date": forecast.dates[i],
                    "predicted_value": predicted,
                    "lower": forecast.lower[i],
                    "upper": forecast.upper[i],
                    "horizon": horizon,
                }
            },
        )

    return AlertEvaluationResult(value=values[-1], breaches=[], interval=interval_value)


def evaluate_with_forecast(
    result: ExtractionResult, forecast_config: dict[str, Any], threshold: InsightThreshold | None
) -> AlertEvaluationResult:
    """Evaluate an extracted trends series against a forecast (the third alert path). Dispatches to
    ``_evaluate_band_deviation`` or ``_evaluate_future_breach`` by ``forecast_config["condition"]``."""
    interval_value = result.interval_type.value if result.interval_type else None

    if not result.series:
        value: float | None = 0 if result.empty_query_result else None
        return AlertEvaluationResult(value=value, breaches=[], interval=interval_value)

    dates, values = _clean_points(result)
    condition = forecast_config.get("condition")
    min_points = min_forecast_points(result.interval_type)
    # band_deviation holds out the latest point as the actual to compare against, fitting on one
    # fewer point than it's given — so it needs one extra point to still fit on a full min_points window.
    required_points = min_points + 1 if condition == ForecastConditionType.BAND_DEVIATION.value else min_points
    if len(values) < required_points:
        raise AlertExtractionError(
            f"Not enough history to forecast: need at least {required_points} completed intervals, "
            f"got {len(values)}. The alert will work once the insight has more data."
        )

    label = result.series[0].label
    interval_width = float(forecast_config.get("interval_width") or DEFAULT_INTERVAL_WIDTH)
    engine = get_forecast_engine(forecast_config)

    if condition == ForecastConditionType.BAND_DEVIATION.value:
        return _evaluate_band_deviation(
            dates, values, label, engine, interval_width, result.interval_type, interval_value
        )
    elif condition == ForecastConditionType.FUTURE_BREACH.value:
        return _evaluate_future_breach(
            dates,
            values,
            label,
            forecast_config,
            engine,
            interval_width,
            result.interval_type,
            threshold,
            interval_value,
        )
    else:
        raise AlertExtractionError(f"Unknown forecast condition: {condition}")


class TrendsForecastExtractor:
    """Forecast-path extractor for trends insights — same shape as TrendsDetectorExtractor, but the
    lookback is sized by the forecast config instead of a detector window."""

    def extract(
        self, alert: AlertConfiguration, insight: Insight, query: Any, execution_mode: ExecutionMode
    ) -> ExtractionResult:
        forecast_config = alert.forecast_config
        if not forecast_config:
            raise ValueError("TrendsForecastExtractor requires forecast_config — dispatcher invariant violated")
        trends_query = TrendsQuery.model_validate(query)
        series_index = (alert.config or {}).get("series_index", 0)
        return extract_trends_series(
            insight,
            alert.team,
            trends_query,
            _forecast_min_samples(forecast_config),
            execution_mode,
            series_index=series_index,
            user=alert.created_by,
        )

    def simulate(self, insight: Insight, query: object, ctx: SimulationContext) -> tuple[ExtractionResult, str | None]:
        trends_query = TrendsQuery.model_validate(query)
        execution_mode = execution_mode_for_alert(trends_query.interval, high_frequency=False)
        result = extract_trends_series(
            insight,
            ctx.team,
            trends_query,
            _forecast_min_samples(ctx.extractor_config),
            execution_mode,
            series_index=ctx.series_index,
            date_from=ctx.date_from,
            user=ctx.user,
        )
        interval_value = trends_query.interval.value if trends_query.interval else None
        return result, interval_value


def simulate_forecast_on_insight(
    insight: Insight,
    team: Team,
    forecast_config: dict[str, Any],
    series_index: int = 0,
    date_from: str | None = None,
    user: Optional[User] = None,
) -> dict[str, Any]:
    """Run a forecast over historical insight data for chart visualization. Read-only (no AlertCheck)."""
    if insight.query is None:
        raise ValueError("Insight has no valid query.")

    with upgrade_query(insight):
        query = insight.query

    kind = get_from_dict_or_attr(query, "kind")
    if kind in WRAPPER_NODE_KINDS:
        query = get_from_dict_or_attr(query, "source")
        kind = get_from_dict_or_attr(query, "kind")

    tag_queries(product=Product.PRODUCT_ANALYTICS, feature=Feature.ALERTING)

    from products.alerts.backend.evaluation.dispatcher import (  # noqa: PLC0415 — breaks dispatcher↔forecast import cycle
        FORECAST_EXTRACTORS,
    )

    extractor = FORECAST_EXTRACTORS.get(kind)
    if extractor is None:
        raise ValueError(f"Forecast simulation isn't supported for {kind} insights")

    ctx = SimulationContext(
        team=team, extractor_config=forecast_config, user=user, series_index=series_index, date_from=date_from
    )
    result, interval_value = extractor.simulate(insight, query, ctx)

    if not result.series:
        if result.empty_query_result:
            raise ValueError("No results found for insight.")
        raise ValueError("Not enough data points to forecast.")

    dates, values = _clean_points(result)
    min_points = min_forecast_points(result.interval_type)
    if len(values) < min_points:
        raise ValueError(
            f"Not enough history to forecast: need at least {min_points} completed intervals, got {len(values)}."
        )

    horizon = int(forecast_config.get("horizon") or DEFAULT_HORIZON)
    interval_width = float(forecast_config.get("interval_width") or DEFAULT_INTERVAL_WIDTH)
    forecast = get_forecast_engine(forecast_config).forecast(
        dates, values, horizon, interval_width, IntervalType(interval_value) if interval_value else None
    )
    return {
        "data": values,
        "dates": dates,
        "interval": interval_value,
        "forecast_dates": forecast.dates,
        "forecast_yhat": forecast.yhat,
        "forecast_lower": forecast.lower,
        "forecast_upper": forecast.upper,
        "forecast_components": forecast.components,
        "fit_quality": {
            "mape": forecast.fit_mape,
            "coverage": forecast.fit_coverage,
            "verdict": _fit_verdict(forecast.fit_mape, forecast.fit_coverage, interval_width),
        },
    }


def _fit_verdict(mape: float | None, coverage: float | None, interval_width: float) -> str:
    """Distill in-sample fit stats into a user-facing verdict so the preview can warn about
    unreliable fits (thresholds per the design spec's fit-quality section)."""
    if mape is None or coverage is None:
        return "unknown"
    coverage_gap = abs(coverage - interval_width)
    if mape < 0.10 and coverage_gap <= 0.05:
        return "good"
    if mape <= 0.30 and coverage_gap <= 0.15:
        return "noisy"
    return "poor"
