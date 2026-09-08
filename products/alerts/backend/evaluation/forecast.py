import math
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.schema import (
    ChartDisplayType,
    ForecastConfig,
    FutureBreachForecastConfig,
    InsightsThresholdBounds,
    InsightThreshold,
    IntervalType,
    TargetByDateForecastConfig,
    TrendsQuery,
)

from posthog.api.services.query import ExecutionMode
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.interval_specs import interval_spec
from posthog.models.team import Team
from posthog.models.user import User
from posthog.schema_migrations.upgrade_manager import upgrade_insight
from posthog.tasks.alerts.trends import _has_breakdown
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, AlertEvaluationResult, is_non_time_series_trend
from posthog.utils import get_from_dict_or_attr, relative_date_parse

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ExtractionResult,
    InsufficientHistoryError,
    SimulationContext,
)
from products.alerts.backend.evaluation.detector import extract_trends_series
from products.alerts.backend.evaluation.formatting import make_trends_value_formatter
from products.alerts.backend.forecasting.engine import (
    DEFAULT_INTERVAL_WIDTH,
    MAX_FORECAST_OUTPUT_POINTS,
    MAX_FORECAST_REACH_DAYS,
    ForecastConfigurationError,
    ForecastResult,
    bounded_lookback_days,
    bounded_training_points,
    default_horizon,
    get_forecast_engine,
    horizon_for_target_date,
    intervals_between,
    min_forecast_points,
    validate_forecast_days_of_week,
    validate_forecast_display,
    validate_forecast_horizon,
    validate_forecast_interval,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


def _parse_config(forecast_config: dict[str, Any]) -> FutureBreachForecastConfig | TargetByDateForecastConfig:
    return ForecastConfig.model_validate(forecast_config).root


def _horizon_from_config(
    config: FutureBreachForecastConfig | TargetByDateForecastConfig,
    interval: IntervalType | None,
    start_date: date,
) -> int:
    if isinstance(config, FutureBreachForecastConfig):
        return config.horizon if config.horizon is not None else default_horizon(interval)

    target_date = date.fromisoformat(config.target_date)
    days = (target_date - start_date).days
    if days <= 0:
        raise InsufficientHistoryError("The forecast has no completed forecast bucket on or before the target date.")
    if days > MAX_FORECAST_REACH_DAYS:
        raise InsufficientHistoryError(
            "This insight has no recent data, so the forecast cannot reach the target date. "
            "The alert will work once the insight is receiving data again."
        )
    horizon = intervals_between(start_date, target_date, interval)
    if horizon > MAX_FORECAST_OUTPUT_POINTS:
        raise InsufficientHistoryError(
            "This insight interval needs too many forecast points to reach the target date. "
            "Use a coarser insight interval."
        )
    return horizon


def _validate_simulation_target_date(
    config: TargetByDateForecastConfig, interval: IntervalType | None, project_timezone: str
) -> None:
    """Bound a preview's target date the same way the create path bounds it.

    validate_forecast_horizon only bounds a future_breach horizon, so an out-of-range target date
    stays unbounded until extraction raises InsufficientHistoryError. That error is not a ValueError,
    so the endpoint cannot map it to a 400 and returns a 500 instead. This check also makes a preview
    report the same message that saving the alert reports.
    """
    try:
        target_date = date.fromisoformat(config.target_date)
    except ValueError:
        raise ValueError(f"Target date isn't a valid date: {config.target_date}")
    horizon_for_target_date(target_date, interval, datetime.now(ZoneInfo(project_timezone)).date())


def _required_history_points(horizon: int, interval: IntervalType | None) -> int:
    return max(min_forecast_points(interval), 4 * horizon)


def _last_completed_bucket(now: datetime, interval: IntervalType | None, week_start_day: int | None) -> date:
    spec = interval_spec(interval)
    return (spec.align(now, week_start_day) - spec.period).date()


def _forecast_extraction_contract(
    forecast_config: dict[str, Any],
    interval: IntervalType | None,
    now: datetime,
    week_start_day: int | None,
) -> tuple[int, date | None]:
    """Pin target history sizing and evaluation to one completed-bucket anchor."""
    config = _parse_config(forecast_config)
    if isinstance(config, FutureBreachForecastConfig):
        return _horizon_from_config(config, interval, now.date()), None

    target_date = date.fromisoformat(config.target_date)
    try:
        # Reach is measured from the project-local calendar day. The completed bucket is one
        # interval earlier and would incorrectly reject valid dates at the 92-day boundary.
        horizon_for_target_date(target_date, interval, now.date())
    except ValueError as error:
        raise InsufficientHistoryError(str(error)) from error

    reference_date = _last_completed_bucket(now, interval, week_start_day)
    horizon = intervals_between(reference_date, target_date, interval)
    if horizon > MAX_FORECAST_OUTPUT_POINTS:
        raise InsufficientHistoryError(
            "This insight interval needs too many forecast points to reach the target date. "
            "Use a coarser insight interval."
        )
    return horizon, reference_date


def _forecast_min_samples(horizon: int, interval: IntervalType | None = None) -> int:
    return bounded_training_points(_required_history_points(horizon, interval), interval)


def _with_resolved_interval(query: TrendsQuery) -> TrendsQuery:
    """The query extraction runs, with a null interval resolved to the daily default.

    A stored query can hold an explicit null interval. The trends runner and every forecast helper
    read that as daily, but the shared history-range picker reads it as hourly. The alert would then
    ask for hours of history to fill daily buckets and never hold enough points to evaluate.
    """
    if query.interval is not None:
        return query
    return query.model_copy(update={"interval": IntervalType.DAY})


def _bounded_simulation_date_from(
    date_from: str | None, timezone: ZoneInfo, today: date, interval: IntervalType | None
) -> str | None:
    """Cap an optional preview range before it reaches the insight query.

    ``bounded_training_points`` limits what Prophet receives, but applying that limit after the
    insight query would still let a caller request an arbitrarily expensive history scan. The cap
    follows the interval, because an hourly fit keeps far less history than the duration limit
    allows and the extra rows reach neither the fit nor the response.
    """
    if date_from is None:
        return None
    earliest_date = today - timedelta(days=bounded_lookback_days(interval))
    try:
        requested_date = relative_date_parse(date_from, timezone).date()
    except (OverflowError, ValueError) as error:
        raise ValueError("Forecast simulation date range is invalid.") from error
    return earliest_date.isoformat() if requested_date < earliest_date else date_from


def _clean_points(result: ExtractionResult) -> tuple[list[str], list[float]]:
    series = result.series[0]
    # Keyed by date so a repeated bucket label collapses. An hourly insight renders both sides of a
    # daylight saving fall-back to the same local time. Prophet drops duplicate history dates while
    # fitting, so passing them on makes it return fewer points than the requested horizon, and the
    # engine then pairs its forecast against a longer margin list and fails.
    points: dict[str, float] = {}
    for point in series.points:
        if point.date is not None and point.value is not None and math.isfinite(point.value):
            points[point.date] = point.value
    limit = bounded_training_points(len(points), result.interval_type)
    dates = list(points)[-limit:]
    return dates, [points[date] for date in dates]


def _inconclusive(result: ExtractionResult, reason: str) -> AlertEvaluationResult:
    return AlertEvaluationResult(
        value=None,
        breaches=[],
        is_inconclusive=True,
        interval=result.interval_type.value if result.interval_type else None,
        triggered_metadata={"forecast": {"status": "inconclusive", "reason": reason}},
    )


def _format_value(result: ExtractionResult, value: float) -> str:
    if result.value_formatter:
        return result.value_formatter(value)
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _actual_breach(
    result: ExtractionResult,
    dates: list[str],
    values: list[float],
    bounds: InsightsThresholdBounds,
) -> AlertEvaluationResult | None:
    actual = values[-1]
    actual_display = _format_value(result, actual)
    label = result.series[0].label
    message: str | None = None
    if bounds.upper is not None and actual > bounds.upper:
        message = (
            f"The latest value for {label} ({actual_display}) is more than the upper threshold "
            f"({_format_value(result, bounds.upper)})."
        )
    elif bounds.lower is not None and actual < bounds.lower:
        message = (
            f"The latest value for {label} ({actual_display}) is less than the lower threshold "
            f"({_format_value(result, bounds.lower)})."
        )
    if message is None:
        return None
    return AlertEvaluationResult(
        value=actual,
        breaches=[message],
        interval=result.interval_type.value if result.interval_type else None,
        triggered_metadata={"forecast": {"breach_type": "observed", "actual_date": dates[-1], "actual_value": actual}},
    )


def _forecast_breach(
    result: ExtractionResult,
    forecast: ForecastResult,
    bounds: InsightsThresholdBounds,
    horizon: int,
    fallback_value: float,
) -> AlertEvaluationResult:
    label = result.series[0].label
    interval = result.interval_type.value if result.interval_type else None
    for index, predicted in enumerate(forecast.yhat):
        comparison: str | None = None
        threshold: float | None = None
        if bounds.upper is not None and predicted > bounds.upper:
            comparison = "more than the upper threshold"
            threshold = bounds.upper
        elif bounds.lower is not None and predicted < bounds.lower:
            comparison = "less than the lower threshold"
            threshold = bounds.lower
        if comparison is None or threshold is None:
            continue

        breach_date = forecast.dates[index][:10]
        message = (
            f"The forecast for {label} is {_format_value(result, predicted)} on {breach_date}, "
            f"{comparison} ({_format_value(result, threshold)})."
        )
        return AlertEvaluationResult(
            value=predicted,
            breaches=[message],
            interval=interval,
            triggered_metadata={
                "forecast": {
                    "breach_type": "predicted",
                    "breach_date": forecast.dates[index],
                    "predicted_value": predicted,
                    "lower": forecast.lower[index],
                    "upper": forecast.upper[index],
                    "horizon": horizon,
                }
            },
        )
    return AlertEvaluationResult(value=fallback_value, breaches=[], interval=interval)


def _canonical_target_date(target_date: str) -> str:
    # `date.fromisoformat` also accepts compact (`20261001`) and ISO week (`2026-W40-4`) dates. Those
    # forms do not sort against the `YYYY-MM-DD` forecast bucket labels, so normalize before comparing.
    return date.fromisoformat(target_date).isoformat()


def _index_for_target_date(forecast_dates: list[str], target_date: str) -> int:
    target = _canonical_target_date(target_date)
    eligible = [index for index, forecast_date in enumerate(forecast_dates) if forecast_date[:10] <= target]
    if not eligible:
        raise InsufficientHistoryError("The forecast has no completed forecast bucket on or before the target date.")
    return eligible[-1]


def _evaluate_target(
    result: ExtractionResult,
    forecast: ForecastResult,
    config: TargetByDateForecastConfig,
) -> AlertEvaluationResult:
    target_date = _canonical_target_date(config.target_date)
    index = _index_for_target_date(forecast.dates, target_date)
    predicted = forecast.yhat[index]
    missed = predicted < config.target if config.target_direction.value == "at_least" else predicted > config.target
    interval = result.interval_type.value if result.interval_type else None
    if not missed:
        return AlertEvaluationResult(value=predicted, breaches=[], interval=interval)

    comparison = "below" if config.target_direction.value == "at_least" else "above"
    evaluated_date = forecast.dates[index]
    return AlertEvaluationResult(
        value=predicted,
        breaches=[
            f"The forecast for {result.series[0].label} is {_format_value(result, predicted)} on "
            f"{evaluated_date[:10]}, {comparison} the target of {_format_value(result, config.target)} "
            f"for {target_date}."
        ],
        interval=interval,
        triggered_metadata={
            "forecast": {
                "target": config.target,
                "target_date": target_date,
                "evaluated_date": evaluated_date,
                "predicted_value": predicted,
                "direction": config.target_direction.value,
            }
        },
    )


def evaluate_with_forecast(
    result: ExtractionResult, forecast_config: dict[str, Any], threshold: InsightThreshold | None
) -> AlertEvaluationResult:
    if not result.series:
        return _inconclusive(result, "not_enough_history")

    dates, values = _clean_points(result)
    if not dates:
        return _inconclusive(result, "not_enough_history")

    config = _parse_config(forecast_config)
    try:
        latest_date = date.fromisoformat(dates[-1][:10])
        if result.forecast_last_completed_bucket is not None:
            if latest_date != date.fromisoformat(result.forecast_last_completed_bucket):
                raise InsufficientHistoryError("The insight's latest completed bucket is stale.")
            if result.forecast_horizon is None:
                raise AlertExtractionError("The forecast extraction contract is missing its horizon.")
            horizon = result.forecast_horizon
        else:
            horizon = _horizon_from_config(config, result.interval_type, latest_date)
    except InsufficientHistoryError:
        return _inconclusive(result, "stale_data")
    required_points = _required_history_points(horizon, result.interval_type)
    if len(values) < required_points:
        return _inconclusive(result, "not_enough_history")

    if isinstance(config, FutureBreachForecastConfig):
        bounds = threshold.bounds if threshold else None
        if bounds is None or (bounds.lower is None and bounds.upper is None):
            raise AlertExtractionError("A predicted threshold alert needs an absolute threshold.")
        if actual_breach := _actual_breach(result, dates, values, bounds):
            return actual_breach

    engine = get_forecast_engine(forecast_config)
    try:
        forecast = engine.forecast(
            dates,
            values,
            horizon,
            DEFAULT_INTERVAL_WIDTH,
            result.interval_type,
        )
    except ForecastConfigurationError as error:
        raise AlertExtractionError(str(error)) from error
    if isinstance(config, FutureBreachForecastConfig):
        assert bounds is not None
        return _forecast_breach(result, forecast, bounds, horizon, values[-1])
    try:
        return _evaluate_target(result, forecast, config)
    except InsufficientHistoryError:
        return _inconclusive(result, "no_target_bucket")


class TrendsForecastExtractor:
    def extract(
        self, alert: AlertConfiguration, insight: Insight, query: Any, execution_mode: ExecutionMode
    ) -> ExtractionResult:
        forecast_config = alert.forecast_config
        if not forecast_config:
            raise ValueError("TrendsForecastExtractor requires forecast_config")
        trends_query = _with_resolved_interval(TrendsQuery.model_validate(query))
        series_index = (alert.config or {}).get("series_index", 0)
        now = datetime.now(ZoneInfo(alert.team.timezone))
        horizon, reference_date = _forecast_extraction_contract(
            forecast_config, trends_query.interval, now, getattr(alert.team, "week_start_day", None)
        )
        if reference_date is not None:
            # A pinned target bucket has to come from data computed under this check's clock. A
            # cached result from before the bucket boundary lost that bucket with the ongoing
            # interval, and the evaluation would read the gap as stale source data.
            execution_mode = ExecutionMode.CALCULATE_BLOCKING_ALWAYS
        result = extract_trends_series(
            insight,
            alert.team,
            trends_query,
            _forecast_min_samples(horizon, trends_query.interval),
            execution_mode,
            series_index=series_index,
            user=alert.created_by,
        )
        result.value_formatter = make_trends_value_formatter(trends_query.trendsFilter, alert.team.base_currency)
        result.forecast_horizon = horizon
        result.forecast_last_completed_bucket = reference_date.isoformat() if reference_date is not None else None
        return result

    def simulate(self, insight: Insight, query: object, ctx: SimulationContext) -> tuple[ExtractionResult, str | None]:
        trends_query = _with_resolved_interval(TrendsQuery.model_validate(query))
        team_timezone = ZoneInfo(ctx.team.timezone)
        now = datetime.now(team_timezone)
        today = now.date()
        horizon, reference_date = _forecast_extraction_contract(
            ctx.extractor_config, trends_query.interval, now, getattr(ctx.team, "week_start_day", None)
        )
        result = extract_trends_series(
            insight,
            ctx.team,
            trends_query,
            _forecast_min_samples(horizon, trends_query.interval),
            ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            series_index=ctx.series_index,
            date_from=_bounded_simulation_date_from(ctx.date_from, team_timezone, today, trends_query.interval),
            user=ctx.user,
        )
        result.value_formatter = make_trends_value_formatter(trends_query.trendsFilter, ctx.team.base_currency)
        result.forecast_horizon = horizon
        result.forecast_last_completed_bucket = reference_date.isoformat() if reference_date is not None else None
        interval_value = trends_query.interval.value if trends_query.interval else None
        return result, interval_value


def _target_projection(
    forecast: ForecastResult, config: FutureBreachForecastConfig | TargetByDateForecastConfig
) -> dict[str, Any] | None:
    if not isinstance(config, TargetByDateForecastConfig):
        return None
    target_date = _canonical_target_date(config.target_date)
    try:
        index = _index_for_target_date(forecast.dates, target_date)
    except InsufficientHistoryError as error:
        raise ValueError(str(error)) from error
    predicted = forecast.yhat[index]
    return {
        "predicted": predicted,
        "target": config.target,
        "target_date": target_date,
        "evaluated_date": forecast.dates[index],
        "misses_target": predicted < config.target
        if config.target_direction.value == "at_least"
        else predicted > config.target,
    }


def simulate_forecast_on_insight(
    insight: Insight,
    team: Team,
    forecast_config: dict[str, Any],
    series_index: int = 0,
    date_from: str | None = None,
    user: User | None = None,
) -> dict[str, Any]:
    if insight.query is None:
        raise ValueError("Insight has no valid query.")

    with upgrade_insight(insight):
        query = insight.query

    kind = get_from_dict_or_attr(query, "kind")
    if kind in WRAPPER_NODE_KINDS:
        query = get_from_dict_or_attr(query, "source")
        kind = get_from_dict_or_attr(query, "kind")

    tag_queries(product=Product.PRODUCT_ANALYTICS, feature=Feature.ALERTING)

    from products.alerts.backend.evaluation.dispatcher import (  # noqa: PLC0415 — breaks the dispatcher/forecast import cycle
        FORECAST_EXTRACTORS,
    )

    extractor = FORECAST_EXTRACTORS.get(kind)
    if extractor is None:
        raise ValueError(f"Forecast simulation isn't supported for {kind} insights")

    trends_query = TrendsQuery.model_validate(query)
    if is_non_time_series_trend(trends_query):
        raise ValueError("Forecast alerts require a time series trends insight")
    validate_forecast_display(trends_query.trendsFilter.display if trends_query.trendsFilter else None)
    if _has_breakdown(trends_query):
        raise ValueError("Forecast alerts don't support breakdowns yet")
    if (
        trends_query.trendsFilter
        and trends_query.trendsFilter.display == ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE
    ):
        raise ValueError("Forecast alerts don't support cumulative trends. Use a non-cumulative time series insight.")
    validate_forecast_interval(trends_query.interval)
    validate_forecast_days_of_week(trends_query.dateRange, trends_query.interval)
    parsed = ForecastConfig.model_validate(forecast_config)
    validate_forecast_horizon(parsed, trends_query.interval)
    config = parsed.root
    if isinstance(config, TargetByDateForecastConfig):
        if trends_query.interval == IntervalType.HOUR:
            raise ValueError(
                "Target-by-date forecast alerts don't support hourly insights. Use a daily, weekly, or monthly interval."
            )
        _validate_simulation_target_date(config, trends_query.interval, team.timezone)

    context = SimulationContext(
        team=team,
        extractor_config=forecast_config,
        user=user,
        series_index=series_index,
        date_from=date_from,
    )
    try:
        result, interval_value = extractor.simulate(insight, query, context)
    except InsufficientHistoryError as error:
        # Extraction re-derives the target horizon against its own clock, so a date that passes the
        # check above can still fail here when the project-local day rolls over between the two.
        raise ValueError(str(error)) from error
    if not result.series:
        raise ValueError("Not enough data points to forecast.")

    dates, values = _clean_points(result)
    if not dates:
        raise ValueError("Not enough data points to forecast.")
    try:
        latest_date = date.fromisoformat(dates[-1][:10])
        if result.forecast_last_completed_bucket is not None:
            if latest_date != date.fromisoformat(result.forecast_last_completed_bucket):
                raise InsufficientHistoryError("The insight's latest completed bucket is stale.")
            if result.forecast_horizon is None:
                raise ValueError("The forecast extraction contract is missing its horizon.")
            horizon = result.forecast_horizon
        else:
            horizon = _horizon_from_config(config, result.interval_type, latest_date)
    except InsufficientHistoryError as error:
        raise ValueError(str(error))
    required_points = _required_history_points(horizon, result.interval_type)
    if len(values) < required_points:
        raise ValueError(
            f"Not enough history to forecast: need at least {required_points} completed intervals, got {len(values)}."
        )

    forecast = get_forecast_engine(forecast_config).forecast(
        dates,
        values,
        horizon,
        DEFAULT_INTERVAL_WIDTH,
        result.interval_type,
    )
    return {
        "data": values,
        "dates": dates,
        "interval": interval_value,
        "forecast_dates": forecast.dates,
        "forecast_yhat": forecast.yhat,
        "forecast_lower": forecast.lower,
        "forecast_upper": forecast.upper,
        "target_projection": _target_projection(forecast, config),
    }
