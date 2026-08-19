from collections.abc import Callable
from datetime import date
from typing import Any, Optional

from posthog.schema import ForecastConfig, InsightsThresholdBounds, InsightThreshold, IntervalType, TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team import Team
from posthog.models.user import User
from posthog.schema_enums import ForecastConditionType, ForecastSensitivity, ForecastTargetDirection
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.alerts.trends import _has_breakdown
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, AlertEvaluationResult, is_non_time_series_trend
from posthog.utils import get_from_dict_or_attr

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ExtractionResult,
    InsufficientHistoryError,
    SimulationContext,
)
from products.alerts.backend.evaluation.detector import extract_trends_series
from products.alerts.backend.forecasting.engine import (
    DEFAULT_HORIZON,
    DEFAULT_INTERVAL_WIDTH,
    FORECAST_LOOKBACK_POINTS,
    ForecastEngine,
    ForecastResult,
    bounded_training_points,
    get_forecast_engine,
    horizon_for_target_date,
    min_forecast_points,
    validate_forecast_horizon_and_width,
    validate_forecast_interval,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


def _resolve_horizon(forecast_config: dict[str, Any]) -> int:
    # `or` rather than a get() default so an explicit null or 0 falls back too.
    return int(forecast_config.get("horizon") or DEFAULT_HORIZON)


def _resolve_interval_width(forecast_config: dict[str, Any]) -> float:
    return float(forecast_config.get("interval_width") or DEFAULT_INTERVAL_WIDTH)


def _forecast_min_samples(forecast_config: dict[str, Any], interval: IntervalType | None = None) -> int:
    """Enough history for seasonality plus the horizon we predict past it, bounded so the window
    cannot grow into a multi-year scan on a coarse interval or a huge fit on a fine one."""
    requested = max(FORECAST_LOOKBACK_POINTS, 4 * _resolve_horizon(forecast_config)) + 1
    return bounded_training_points(requested, interval)


def _required_points(condition: str | None, interval_type: IntervalType | None) -> int:
    """How much history a condition needs. band_deviation holds out the latest point as the actual
    to compare against, fitting on one fewer point than it is given, so it needs one extra to still
    fit on a full window. Shared so the preview cannot accept a series the alert then rejects."""
    min_points = min_forecast_points(interval_type)
    if condition == ForecastConditionType.BAND_DEVIATION.value:
        return min_points + 1
    return min_points


def _clean_points(result: ExtractionResult) -> tuple[list[str], list[float]]:
    s = result.series[0]
    dates: list[str] = []
    values: list[float] = []
    for p in s.points:
        if p.date is not None and p.value is not None:
            dates.append(p.date)
            values.append(p.value)
    # Clamp what reaches the engine, rather than trusting how the window was chosen. The simulate
    # caller's date_from wins over the computed minimum whenever it reaches further back, so an
    # absolute date on an hourly insight would otherwise hand Prophet tens of thousands of points.
    limit = bounded_training_points(len(values), result.interval_type)
    return dates[-limit:], values[-limit:]


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
    engine: ForecastEngine,
    interval_width: float,
    interval_type: IntervalType | None,
) -> AlertEvaluationResult:
    """Fit on history excluding the latest completed point, predict one interval, fire if that
    actual point sits outside the band."""
    interval_value = interval_type.value if interval_type else None
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


def _evaluate_future_breach_values(
    *,
    yhat: list[float],
    lower: list[float],
    upper: list[float],
    dates: list[str],
    bounds: InsightsThresholdBounds,
    sensitivity: str,
    label: str,
    horizon: int,
    interval_value: str | None = None,
    fallback_value: float | None = None,
    decomposition: Callable[[int], str] = lambda _i: "",
) -> AlertEvaluationResult:
    """Fire on the first predicted point that crosses a bound. Split out from the fit so the
    sensitivity matrix is testable without an engine.

    `best_case` reads the edge that keeps the metric on the acceptable side, which is the lower
    edge against a ceiling and the upper edge against a floor, so it always fires later.
    """
    best_case = sensitivity == ForecastSensitivity.BEST_CASE.value
    against_upper = lower if best_case else yhat
    against_lower = upper if best_case else yhat

    for i in range(len(yhat)):
        breach_date = dates[i][:10]
        if bounds.upper is not None and against_upper[i] > bounds.upper:
            predicted = against_upper[i]
            message = (
                f"Forecast for {label}: predicted value {predicted:.2f} on {breach_date} "
                f"is more than the upper threshold ({bounds.upper}){decomposition(i)}"
            )
        elif bounds.lower is not None and against_lower[i] < bounds.lower:
            predicted = against_lower[i]
            message = (
                f"Forecast for {label}: predicted value {predicted:.2f} on {breach_date} "
                f"is less than the lower threshold ({bounds.lower}){decomposition(i)}"
            )
        else:
            continue
        return AlertEvaluationResult(
            value=predicted,
            breaches=[message],
            interval=interval_value,
            triggered_metadata={
                "forecast": {
                    "breach_date": dates[i],
                    "predicted_value": predicted,
                    "lower": lower[i],
                    "upper": upper[i],
                    "horizon": horizon,
                    "sensitivity": sensitivity,
                }
            },
        )

    return AlertEvaluationResult(value=fallback_value, breaches=[], interval=interval_value)


def _evaluate_future_breach(
    dates: list[str],
    values: list[float],
    label: str,
    forecast_config: dict[str, Any],
    engine: ForecastEngine,
    interval_width: float,
    interval_type: IntervalType | None,
    threshold: InsightThreshold | None,
) -> AlertEvaluationResult:
    """Fit on the full history, predict `horizon` intervals, fire if the forecast crosses the
    threshold bounds."""
    interval_value = interval_type.value if interval_type else None
    horizon = _resolve_horizon(forecast_config)
    forecast = engine.forecast(dates, values, horizon, interval_width, interval_type)
    bounds = threshold.bounds if threshold else None
    if bounds is None or (bounds.lower is None and bounds.upper is None):
        return AlertEvaluationResult(value=values[-1], breaches=[], interval=interval_value)

    return _evaluate_future_breach_values(
        yhat=forecast.yhat,
        lower=forecast.lower,
        upper=forecast.upper,
        dates=forecast.dates,
        bounds=bounds,
        sensitivity=_resolve_sensitivity(forecast_config),
        label=label,
        horizon=horizon,
        interval_value=interval_value,
        fallback_value=values[-1],
        decomposition=lambda i: _decomposition_suffix(forecast, i),
    )


def _resolve_sensitivity(forecast_config: dict[str, Any]) -> str:
    """Which line the comparison reads. `best_case` is always the edge most favorable to the user,
    so it always fires later than `forecast`.

    The default depends on the condition. A target has months of runway, so flapping is the failure
    mode and the conservative reading wins. A breach alert exists for lead time, so defaulting it to
    the quiet end would blunt the one thing it is for, and it keeps reading the point forecast.
    """
    explicit = forecast_config.get("sensitivity")
    if explicit:
        return str(explicit)
    if forecast_config.get("condition") == ForecastConditionType.FUTURE_BREACH.value:
        return ForecastSensitivity.FORECAST.value
    return ForecastSensitivity.BEST_CASE.value


def _evaluate_target_by_date_values(
    *,
    yhat: float,
    lower: float,
    upper: float,
    target: float,
    direction: str,
    sensitivity: str,
    target_date: str,
    label: str,
) -> AlertEvaluationResult:
    """Compare the value predicted for the target date against the target. Split out from the fit so
    the direction and sensitivity matrix is testable without an engine."""
    best_case = sensitivity == ForecastSensitivity.BEST_CASE.value
    if direction == ForecastTargetDirection.AT_LEAST.value:
        predicted = upper if best_case else yhat
        missed = predicted < target
        comparison = "below"
    else:
        predicted = lower if best_case else yhat
        missed = predicted > target
        comparison = "above"
    if not missed:
        return AlertEvaluationResult(value=yhat, breaches=[], interval=None)
    qualifier = "even in the best case" if best_case else "on the current forecast"
    return AlertEvaluationResult(
        value=predicted,
        breaches=[
            f"Forecast for {label}: predicted {predicted:.2f} on {target_date} is {comparison} "
            f"the target of {target} {qualifier}"
        ],
        interval=None,
        triggered_metadata={
            "forecast": {
                "target": target,
                "target_date": target_date,
                "predicted_value": predicted,
                "direction": direction,
                "sensitivity": sensitivity,
            }
        },
    )


def _evaluate_target_by_date(
    dates: list[str],
    values: list[float],
    label: str,
    forecast_config: dict[str, Any],
    engine: ForecastEngine,
    interval_width: float,
    interval_type: IntervalType | None,
) -> AlertEvaluationResult:
    """Forecast to a fixed calendar date and compare the value predicted there against the target."""
    target = forecast_config.get("target")
    target_date = forecast_config.get("target_date")
    if target is None or not target_date:
        raise AlertExtractionError("A target alert needs both a target and a target date.")
    try:
        # Count from the last completed bucket, which is where Prophet extends from. Counting from
        # today lands the final point one interval short of the date the user asked about.
        horizon = horizon_for_target_date(
            date.fromisoformat(str(target_date)), interval_type, date.fromisoformat(dates[-1][:10])
        )
    except ValueError as e:
        raise AlertExtractionError(str(e))
    forecast = engine.forecast(dates, values, horizon, interval_width, interval_type)
    at = _index_for_target_date(forecast.dates, str(target_date))
    return _evaluate_target_by_date_values(
        yhat=forecast.yhat[at],
        lower=forecast.lower[at],
        upper=forecast.upper[at],
        target=float(target),
        direction=forecast_config.get("target_direction") or ForecastTargetDirection.AT_LEAST.value,
        sensitivity=_resolve_sensitivity(forecast_config),
        target_date=str(target_date),
        label=label,
    )


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
    required_points = _required_points(condition, result.interval_type)
    if len(values) < required_points:
        raise InsufficientHistoryError(
            f"Not enough history to forecast: need at least {required_points} completed intervals, "
            f"got {len(values)}. The alert will work once the insight has more data."
        )

    label = result.series[0].label
    interval_width = _resolve_interval_width(forecast_config)
    engine = get_forecast_engine(forecast_config)

    if condition == ForecastConditionType.BAND_DEVIATION.value:
        return _evaluate_band_deviation(dates, values, label, engine, interval_width, result.interval_type)
    elif condition == ForecastConditionType.TARGET_BY_DATE.value:
        return _evaluate_target_by_date(
            dates, values, label, forecast_config, engine, interval_width, result.interval_type
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
            _forecast_min_samples(forecast_config, trends_query.interval),
            execution_mode,
            series_index=series_index,
            user=alert.created_by,
        )

    def simulate(self, insight: Insight, query: object, ctx: SimulationContext) -> tuple[ExtractionResult, str | None]:
        trends_query = TrendsQuery.model_validate(query)
        # Simulate is an explicit user action, so recompute rather than serve a cached result. A stale
        # cache here shows a preview that disagrees with what the alert would do on the same insight.
        execution_mode = ExecutionMode.CALCULATE_BLOCKING_ALWAYS
        result = extract_trends_series(
            insight,
            ctx.team,
            trends_query,
            _forecast_min_samples(ctx.extractor_config, trends_query.interval),
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

    # Reject the same shapes the save path rejects, before paying for the query. Otherwise the
    # preview is more permissive than saving: a breakdown insight would forecast series[0] and
    # present it as the whole insight.
    trends_query = TrendsQuery.model_validate(query)
    if is_non_time_series_trend(trends_query):
        raise ValueError("Forecast alerts require a time series trends insight")
    if _has_breakdown(trends_query):
        raise ValueError("Forecast alerts don't support breakdowns yet")
    validate_forecast_interval(trends_query.interval)
    validate_forecast_horizon_and_width(ForecastConfig.model_validate(forecast_config), trends_query.interval)

    ctx = SimulationContext(
        team=team, extractor_config=forecast_config, user=user, series_index=series_index, date_from=date_from
    )
    result, interval_value = extractor.simulate(insight, query, ctx)

    if not result.series:
        if result.empty_query_result:
            raise ValueError("No results found for insight.")
        raise ValueError("Not enough data points to forecast.")

    dates, values = _clean_points(result)
    required_points = _required_points(forecast_config.get("condition"), result.interval_type)
    if len(values) < required_points:
        raise ValueError(
            f"Not enough history to forecast: need at least {required_points} completed intervals, got {len(values)}."
        )

    interval_width = _resolve_interval_width(forecast_config)
    interval_type = IntervalType(interval_value) if interval_value else None
    if forecast_config.get("condition") == ForecastConditionType.TARGET_BY_DATE.value:
        target_date = forecast_config.get("target_date")
        if not target_date:
            raise ValueError("A target alert needs a target date.")
        horizon = horizon_for_target_date(
            date.fromisoformat(str(target_date)), interval_type, date.fromisoformat(dates[-1][:10])
        )
    else:
        horizon = _resolve_horizon(forecast_config)
    engine = get_forecast_engine(forecast_config)
    forecast = engine.forecast(dates, values, horizon, interval_width, interval_type, include_history=True)
    return {
        "data": values,
        "dates": dates,
        "interval": interval_value,
        "forecast_dates": forecast.dates,
        "forecast_yhat": forecast.yhat,
        "forecast_lower": forecast.lower,
        "forecast_upper": forecast.upper,
        "forecast_components": forecast.components,
        "history_lower": forecast.history_lower,
        "history_upper": forecast.history_upper,
        "target_projection": _target_projection(forecast, forecast_config),
        "latest_deviation": _latest_deviation(dates, values, forecast_config, engine, interval_width, interval_type),
        "fit_quality": {
            "mape": forecast.fit_mape,
            "coverage": forecast.fit_coverage,
            "verdict": _fit_verdict(forecast.fit_mape, forecast.fit_coverage, interval_width),
        },
    }


def _index_for_target_date(forecast_dates: list[str], target_date: str) -> int:
    """First predicted point that reaches the target date. Prophet extends from the last completed
    bucket rather than from today, so the last point is not the target date."""
    for i, d in enumerate(forecast_dates):
        if d[:10] >= target_date[:10]:
            return i
    return len(forecast_dates) - 1


def _target_projection(forecast: ForecastResult, forecast_config: dict[str, Any]) -> dict[str, Any] | None:
    """Both crossings for the preview: what the forecast says, and what the favorable edge says.
    Returning both is what makes the choice between the two sensitivities visible rather than
    theoretical, so a user can see which one their target sits between."""
    if forecast_config.get("condition") != ForecastConditionType.TARGET_BY_DATE.value:
        return None
    target = forecast_config.get("target")
    if target is None:
        return None
    at_least = (forecast_config.get("target_direction") or ForecastTargetDirection.AT_LEAST.value) == (
        ForecastTargetDirection.AT_LEAST.value
    )
    at = _index_for_target_date(forecast.dates, str(forecast_config.get("target_date") or ""))
    predicted = forecast.yhat[at]
    best_case = forecast.upper[at] if at_least else forecast.lower[at]
    return {
        "predicted": predicted,
        "best_case": best_case,
        "target": float(target),
        "target_date": str(forecast_config.get("target_date") or ""),
        "misses_on_forecast": predicted < target if at_least else predicted > target,
        "misses_on_best_case": best_case < target if at_least else best_case > target,
    }


def _latest_deviation(
    dates: list[str],
    values: list[float],
    forecast_config: dict[str, Any],
    engine: ForecastEngine,
    interval_width: float,
    interval_type: IntervalType | None,
) -> dict[str, Any] | None:
    """The band-deviation check the alert would actually run, so the preview and the evaluation can't
    disagree. Costs a second fit, so only the condition that uses it pays for it."""
    if forecast_config.get("condition") != ForecastConditionType.BAND_DEVIATION.value:
        return None
    held_out = engine.forecast(dates[:-1], values[:-1], 1, interval_width, interval_type)
    actual = values[-1]
    lower, upper = held_out.lower[0], held_out.upper[0]
    return {"value": actual, "lower": lower, "upper": upper, "outside": actual < lower or actual > upper}


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
