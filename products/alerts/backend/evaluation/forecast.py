from collections.abc import Callable
from datetime import date
from typing import Any, Optional

from posthog.schema import ForecastConfig, InsightsThresholdBounds, InsightThreshold, IntervalType, TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team import Team
from posthog.models.user import User
from posthog.schema_enums import (
    ForecastConditionType,
    ForecastDirection,
    ForecastErrorMode,
    ForecastSensitivity,
    ForecastTargetDirection,
)
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
    intervals_between,
    max_evaluable_horizon,
    min_forecast_points,
    validate_forecast_horizon_and_width,
    validate_forecast_interval,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


def _resolve_horizon(forecast_config: dict[str, Any]) -> int:
    return int(forecast_config.get("horizon") or DEFAULT_HORIZON)


def _resolve_interval_width(forecast_config: dict[str, Any]) -> float:
    return float(forecast_config.get("interval_width") or DEFAULT_INTERVAL_WIDTH)


def _forecast_min_samples(forecast_config: dict[str, Any], interval: IntervalType | None = None) -> int:
    requested = max(FORECAST_LOOKBACK_POINTS, 4 * _resolve_horizon(forecast_config)) + 1
    return bounded_training_points(requested, interval)


def _required_points(condition: str | None, interval_type: IntervalType | None) -> int:
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
    limit = bounded_training_points(len(values), result.interval_type)
    return dates[-limit:], values[-limit:]


def _decomposition_suffix(forecast: ForecastResult, index: int) -> str:
    if not forecast.components:
        return ""
    trend_series = forecast.components.get("trend")
    trend = trend_series[index] if trend_series and index < len(trend_series) else None
    if trend is None:
        return ""

    parts = [f"usual level around {trend:,.0f}"]
    if trend > 0:
        for name, phrasing in (("weekly", "on this day of the week"), ("yearly", "at this time of year")):
            series = forecast.components.get(name)
            if not series or index >= len(series):
                continue
            share = series[index] / trend
            direction = "higher" if share >= 0 else "lower"
            parts.append(f"typically {abs(share):.0%} {direction} {phrasing}")
    return f" ({', '.join(parts)})"


def _band_deviation_verdict(
    *,
    actual: float,
    yhat: float,
    lower: float,
    upper: float,
    direction: str,
    error_mode: str,
    error_threshold_pct: float | None,
    error_threshold_abs: float | None,
    score_threshold: float,
) -> tuple[bool, str]:
    half_width = max((upper - lower) / 2, 0.0)
    if error_mode == ForecastErrorMode.RELATIVE.value:
        denominator = max(abs(yhat), half_width)
        deviation = abs(actual - yhat) / denominator if denominator else 0.0
        outside = deviation > (error_threshold_pct or 0.0)
        described = f"within {(error_threshold_pct or 0.0):.0%} of {yhat:.2f}"
    elif error_mode == ForecastErrorMode.ABSOLUTE.value:
        allowed = error_threshold_abs or 0.0
        outside = abs(actual - yhat) > allowed
        described = f"within {allowed:.2f} of {yhat:.2f}"
    else:
        outside = actual < lower or actual > upper
        described = f"{lower:.2f} to {upper:.2f}"
        if outside and score_threshold > 0 and half_width > 0:
            excess = (actual - upper) if actual > upper else (lower - actual)
            outside = (excess / half_width) >= score_threshold

    if not outside:
        return False, described
    moved_up = actual > yhat
    if direction == ForecastDirection.ABOVE.value and not moved_up:
        return False, described
    if direction == ForecastDirection.BELOW.value and moved_up:
        return False, described
    return True, described


def _evaluate_band_deviation(
    dates: list[str],
    values: list[float],
    label: str,
    engine: ForecastEngine,
    interval_width: float,
    interval_type: IntervalType | None,
    forecast_config: dict[str, Any] | None = None,
) -> AlertEvaluationResult:
    config = forecast_config or {}
    interval_value = interval_type.value if interval_type else None
    forecast = engine.forecast(dates[:-1], values[:-1], 1, interval_width, interval_type)
    actual = values[-1]
    lower, upper, yhat = forecast.lower[0], forecast.upper[0], forecast.yhat[0]

    fired, described = _band_deviation_verdict(
        actual=actual,
        yhat=yhat,
        lower=lower,
        upper=upper,
        direction=config.get("direction") or ForecastDirection.BOTH.value,
        error_mode=config.get("error_mode") or ForecastErrorMode.PREDICTION_INTERVAL.value,
        error_threshold_pct=config.get("error_threshold_pct"),
        error_threshold_abs=config.get("error_threshold_abs"),
        score_threshold=float(config.get("score_threshold") or 0.0),
    )

    breaches: list[str] = []
    if fired:
        breaches = [
            f"The latest value for {label} ({actual:.2f}) is outside the expected range "
            f"({described}){_decomposition_suffix(forecast, 0)}"
        ]
    return AlertEvaluationResult(
        value=actual,
        breaches=breaches,
        interval=interval_value,
        triggered_metadata={"forecast": {"lower": lower, "upper": upper, "yhat": yhat}} if breaches else None,
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
    best_case = sensitivity == ForecastSensitivity.BEST_CASE.value
    against_upper = lower if best_case else yhat
    against_lower = upper if best_case else yhat

    qualifier = "even in the best case" if best_case else "on the current forecast"
    for i in range(len(yhat)):
        breach_date = dates[i][:10]
        if bounds.upper is not None and against_upper[i] > bounds.upper:
            predicted = against_upper[i]
            message = (
                f"Forecast for {label}: predicted {predicted:.2f} on {breach_date} "
                f"is more than the upper threshold ({bounds.upper}) {qualifier}{decomposition(i)}"
            )
        elif bounds.lower is not None and against_lower[i] < bounds.lower:
            predicted = against_lower[i]
            message = (
                f"Forecast for {label}: predicted {predicted:.2f} on {breach_date} "
                f"is less than the lower threshold ({bounds.lower}) {qualifier}{decomposition(i)}"
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
    target = forecast_config.get("target")
    target_date = forecast_config.get("target_date")
    if target is None or not target_date:
        raise AlertExtractionError("A target alert needs both a target and a target date.")
    horizon = intervals_between(date.fromisoformat(dates[-1][:10]), date.fromisoformat(str(target_date)), interval_type)
    if horizon > max_evaluable_horizon(interval_type):
        raise InsufficientHistoryError(
            "This insight has no recent data, so the forecast cannot reach the target date. "
            "The alert will work once the insight is receiving data again."
        )
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
        return _evaluate_band_deviation(
            dates, values, label, engine, interval_width, result.interval_type, forecast_config
        )
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
        horizon = intervals_between(
            date.fromisoformat(dates[-1][:10]), date.fromisoformat(str(target_date)), interval_type
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
    for i, d in enumerate(forecast_dates):
        if d[:10] >= target_date[:10]:
            return i
    return len(forecast_dates) - 1


def _target_projection(forecast: ForecastResult, forecast_config: dict[str, Any]) -> dict[str, Any] | None:
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
    if forecast_config.get("condition") != ForecastConditionType.BAND_DEVIATION.value:
        return None
    held_out = engine.forecast(dates[:-1], values[:-1], 1, interval_width, interval_type)
    actual = values[-1]
    lower, upper = held_out.lower[0], held_out.upper[0]
    return {"value": actual, "lower": lower, "upper": upper, "outside": actual < lower or actual > upper}


def _fit_verdict(mape: float | None, coverage: float | None, interval_width: float) -> str:
    if mape is None or coverage is None:
        return "unknown"
    coverage_gap = abs(coverage - interval_width)
    if mape < 0.10 and coverage_gap <= 0.05:
        return "good"
    if mape <= 0.30 and coverage_gap <= 0.15:
        return "noisy"
    return "poor"
