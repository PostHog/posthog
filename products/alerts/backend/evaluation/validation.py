from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError as PydanticValidationError

from posthog.schema import (
    AlertCalculationInterval,
    AlertCondition,
    AlertConditionType,
    FunnelsAlertConfig,
    FunnelsQuery,
    HogQLAlertConfig,
    HogQLAlertEvaluation,
    InsightThreshold,
    InsightThresholdType,
    IntervalType,
    NodeKind,
    TrendsAlertConfig,
    TrendsQuery,
)

from posthog.tasks.alerts.utils import REAL_TIME_CADENCE_MINUTES, WRAPPER_NODE_KINDS, is_non_time_series_trend
from posthog.utils import get_from_dict_or_attr

from products.alerts.backend.evaluation.dispatcher import DETECTOR_EXTRACTORS
from products.alerts.backend.evaluation.funnel_strategies import strategy_for_viz

THRESHOLD_BOUNDS_REQUIRED_MESSAGE = "At least one threshold bound (lower or upper) must be provided."


@dataclass(frozen=True)
class _AlertConfigValidationContext:
    """Everything a per-config-type validator needs, after the common checks have run."""

    config: dict
    query: dict
    query_kind: str | None
    parsed_condition: AlertCondition
    threshold_config: dict | None
    require_threshold_bounds: bool
    detector_config: dict | None


def insight_threshold_has_bounds(threshold_config: dict | None) -> bool:
    if threshold_config is None:
        return False
    try:
        threshold = InsightThreshold.model_validate(threshold_config)
    except PydanticValidationError:
        return False
    bounds = threshold.bounds
    if bounds is None:
        return False
    return bounds.lower is not None or bounds.upper is not None


def validate_threshold_bounds_required(threshold_config: dict | None) -> None:
    if not insight_threshold_has_bounds(threshold_config):
        raise ValueError(THRESHOLD_BOUNDS_REQUIRED_MESSAGE)


def _validate_condition_threshold_compatibility(
    parsed_condition: AlertCondition, threshold_config: dict | None
) -> InsightThreshold | None:
    """Parse the threshold and enforce condition/threshold compatibility shared by all insight kinds."""
    if threshold_config is None:
        return None
    try:
        threshold = InsightThreshold.model_validate(threshold_config)
    except Exception:
        raise ValueError(f"Alert has invalid threshold configuration: {threshold_config}")
    if parsed_condition.type == AlertConditionType.ABSOLUTE_VALUE and threshold.type != InsightThresholdType.ABSOLUTE:
        raise ValueError(
            "Absolute value alerts require an absolute threshold, but a percentage threshold was configured"
        )
    return threshold


def _validate_hogql_alert_config(ctx: _AlertConfigValidationContext) -> None:
    # SQL insights own their time window; there is no series_index or ongoing-interval concept,
    # so the query kind, evaluation mode, condition/threshold compatibility, and bounds are validated.
    if ctx.query_kind != NodeKind.HOG_QL_QUERY:
        raise ValueError(f"SQL alert config requires a HogQLQuery insight, got '{ctx.query_kind}'")
    try:
        parsed = HogQLAlertConfig.model_validate(ctx.config)
    except Exception:
        raise ValueError(f"Alert has invalid HogQLAlertConfig: {ctx.config}")
    if parsed.evaluation == HogQLAlertEvaluation.ANY_ROW and ctx.parsed_condition.type != (
        AlertConditionType.ABSOLUTE_VALUE
    ):
        # Rows are entities in any_row mode, not a time axis — relative change is meaningless.
        raise ValueError("Any-row SQL alerts only support absolute value conditions")
    if ctx.detector_config is not None and parsed.evaluation == HogQLAlertEvaluation.ANY_ROW:
        # Same reason anomaly detection rejects any_row at evaluation time: its rows aren't a time
        # series. Reject at config time so the alert can't be saved only to fail every check.
        raise ValueError("Anomaly detection isn't supported for any-row SQL alerts — use last-row or first-row")
    _validate_condition_threshold_compatibility(ctx.parsed_condition, ctx.threshold_config)
    if ctx.require_threshold_bounds and ctx.detector_config is None:
        validate_threshold_bounds_required(ctx.threshold_config)


def _validate_trends_alert_config(ctx: _AlertConfigValidationContext) -> None:
    try:
        parsed_config = TrendsAlertConfig.model_validate(ctx.config)
    except Exception:
        raise ValueError(f"Alert has invalid TrendsAlertConfig: {ctx.config}")

    if ctx.query_kind != NodeKind.TRENDS_QUERY:
        raise ValueError(f"Alert's insight query kind '{ctx.query_kind}' is not supported (only TrendsQuery)")

    try:
        trends_query = TrendsQuery.model_validate(ctx.query)
    except Exception as e:
        raise ValueError(f"Alert's insight has an invalid TrendsQuery: {e}")

    if ctx.parsed_condition.type in (
        AlertConditionType.RELATIVE_INCREASE,
        AlertConditionType.RELATIVE_DECREASE,
    ) and is_non_time_series_trend(trends_query):
        raise ValueError(
            f"Relative alert condition '{ctx.parsed_condition.type}' is not compatible with non time series trends"
        )

    formula_nodes = trends_query.trendsFilter.formulaNodes if trends_query.trendsFilter else None
    result_count = len(formula_nodes) if formula_nodes else len(trends_query.series)
    if parsed_config.series_index >= result_count:
        raise ValueError(f"series_index {parsed_config.series_index} is out of range (query has {result_count} series)")

    threshold = _validate_condition_threshold_compatibility(ctx.parsed_condition, ctx.threshold_config)
    if (
        threshold is not None
        and parsed_config.check_ongoing_interval
        and ctx.parsed_condition.type
        in (
            AlertConditionType.ABSOLUTE_VALUE,
            AlertConditionType.RELATIVE_INCREASE,
        )
    ):
        if not threshold.bounds or threshold.bounds.upper is None:
            raise ValueError(
                f"check_ongoing_interval is only supported for alert condition {ctx.parsed_condition.type} when upper threshold is specified"
            )

    if ctx.require_threshold_bounds and ctx.detector_config is None:
        validate_threshold_bounds_required(ctx.threshold_config)


def _validate_funnels_alert_config(ctx: _AlertConfigValidationContext) -> None:
    if ctx.query_kind != NodeKind.FUNNELS_QUERY:
        raise ValueError(f"Funnel alert config requires a FunnelsQuery insight, got '{ctx.query_kind}'")
    try:
        parsed = FunnelsAlertConfig.model_validate(ctx.config)
    except Exception:
        raise ValueError(f"Alert has invalid FunnelsAlertConfig: {ctx.config}")
    try:
        funnels_query = FunnelsQuery.model_validate(ctx.query)
    except Exception as e:
        raise ValueError(f"Alert's insight has an invalid FunnelsQuery: {e}")
    # Resolve the strategy first (rejects unsupported viz types), then delegate viz-specific rules to
    # the same strategy the extractor uses at eval time, so config-time and eval-time views can't drift.
    viz = funnels_query.funnelsFilter.funnelVizType if funnels_query.funnelsFilter else None
    strategy = strategy_for_viz(viz)
    # Relative conditions need a prior value, which only a time-series viz (historical trends) has.
    if ctx.parsed_condition.type != AlertConditionType.ABSOLUTE_VALUE and not strategy.supports_relative_conditions:
        raise ValueError("This funnel only supports absolute value conditions")
    strategy.validate_config(funnels_query, parsed)
    _validate_condition_threshold_compatibility(ctx.parsed_condition, ctx.threshold_config)
    if ctx.require_threshold_bounds and ctx.detector_config is None:
        validate_threshold_bounds_required(ctx.threshold_config)


# Per-config-type validators, mirroring the extractor registry in dispatcher.py: one entry per
# config type the threshold path supports. Adding a kind = adding an entry here and an extractor.
_ALERT_CONFIG_VALIDATORS: dict[str, Callable[[_AlertConfigValidationContext], None]] = {
    "HogQLAlertConfig": _validate_hogql_alert_config,
    "TrendsAlertConfig": _validate_trends_alert_config,
    "FunnelsAlertConfig": _validate_funnels_alert_config,
}


# Twin of CADENCE_DURATION_MINUTES / INSIGHT_INTERVAL_DURATION_MINUTES in
# products/alerts/frontend/logic/alertIntervalHelpers.ts — keep the two in sync.
_CADENCE_DURATION_MINUTES: dict[AlertCalculationInterval, float] = {
    AlertCalculationInterval.REAL_TIME: REAL_TIME_CADENCE_MINUTES,
    AlertCalculationInterval.EVERY_15_MINUTES: 15,
    AlertCalculationInterval.HOURLY: 60,
    AlertCalculationInterval.DAILY: 60 * 24,
    AlertCalculationInterval.WEEKLY: 60 * 24 * 7,
    AlertCalculationInterval.MONTHLY: 60 * 24 * 30,
}

_INTERVAL_DURATION_MINUTES: dict[IntervalType, float] = {
    IntervalType.SECOND: 1 / 60,
    IntervalType.MINUTE: 1,
    IntervalType.HOUR: 60,
    IntervalType.DAY: 60 * 24,
    IntervalType.WEEK: 60 * 24 * 7,
    IntervalType.MONTH: 60 * 24 * 30,
}


def _cadence_finer_than_interval(cadence: AlertCalculationInterval, insight_interval: IntervalType | None) -> bool:
    interval_minutes = _INTERVAL_DURATION_MINUTES.get(
        insight_interval or IntervalType.DAY, _INTERVAL_DURATION_MINUTES[IntervalType.DAY]
    )
    return _CADENCE_DURATION_MINUTES[cadence] < interval_minutes


def _threshold_has_upper_bound(threshold_config: dict | None) -> bool:
    if threshold_config is None:
        return False
    try:
        threshold = InsightThreshold.model_validate(threshold_config)
    except PydanticValidationError:
        return False
    return threshold.bounds is not None and threshold.bounds.upper is not None


def should_default_check_ongoing_interval(
    *,
    query: dict,
    config: dict | None,
    condition: dict | None,
    threshold_config: dict | None,
    calculation_interval: str | None,
) -> bool:
    """Whether an alert left with ``check_ongoing_interval`` unset should default it on.

    A cadence finer than the insight's grouping interval re-checks a frozen completed bucket until it
    closes, so evaluating the ongoing (incomplete) bucket is what makes the faster cadence meaningful.
    Only applies where the toggle is valid — mirrors the UI's ``canCheckOngoingInterval``: a trends
    absolute/increase alert above an upper bound, or a time-series (historical-trend) funnel.
    """
    if not isinstance(config, dict) or calculation_interval is None:
        return False
    try:
        cadence = AlertCalculationInterval(calculation_interval)
    except ValueError:
        return False

    kind = get_from_dict_or_attr(query, "kind")
    if kind in WRAPPER_NODE_KINDS:
        query = get_from_dict_or_attr(query, "source")

    config_type = config.get("type")
    if config_type == "TrendsAlertConfig":
        try:
            trends_query = TrendsQuery.model_validate(query)
            parsed_condition = AlertCondition.model_validate(condition)
        except PydanticValidationError:
            return False
        if is_non_time_series_trend(trends_query):
            return False
        if parsed_condition.type not in (AlertConditionType.ABSOLUTE_VALUE, AlertConditionType.RELATIVE_INCREASE):
            return False
        return _cadence_finer_than_interval(cadence, trends_query.interval) and _threshold_has_upper_bound(
            threshold_config
        )

    if config_type == "FunnelsAlertConfig":
        try:
            funnels_query = FunnelsQuery.model_validate(query)
        except PydanticValidationError:
            return False
        viz = funnels_query.funnelsFilter.funnelVizType if funnels_query.funnelsFilter else None
        try:
            strategy = strategy_for_viz(viz)
        except ValueError:
            return False
        # Time-series funnels only (steps funnels have no periods) — the same gate as isTrendsFunnel.
        return strategy.supports_relative_conditions and _cadence_finer_than_interval(cadence, funnels_query.interval)

    return False


def validate_alert_config(
    query: dict,
    condition: dict | None,
    config: dict | None,
    threshold_config: dict | None = None,
    calculation_interval: str | None = None,
    detector_config: dict | None = None,
    require_threshold_bounds: bool = True,
) -> None:
    """Validate alert configuration dicts. Raises ValueError on failure.

    Common checks run here; per-config-type rules live in ``_ALERT_CONFIG_VALIDATORS``.
    """
    if not calculation_interval or not isinstance(calculation_interval, str):
        raise ValueError(f"Invalid calculation interval: {calculation_interval}")
    try:
        AlertCalculationInterval(calculation_interval)
    except ValueError:
        raise ValueError(f"Invalid calculation interval: {calculation_interval}")

    try:
        parsed_condition = AlertCondition.model_validate(condition)
    except Exception:
        raise ValueError(f"Alert has invalid condition: {condition}")

    config_type = config.get("type") if isinstance(config, dict) else None

    kind = get_from_dict_or_attr(query, "kind")
    if kind in WRAPPER_NODE_KINDS:
        query = get_from_dict_or_attr(query, "source")
        kind = get_from_dict_or_attr(query, "kind")

    # The detector path supports only the kinds with a detector extractor — a non-supported detector
    # alert would raise at evaluation time, so reject it here at configuration time. Reading the
    # dispatcher's registry directly keeps the config-time and evaluation-time views from drifting.
    if detector_config is not None and kind not in DETECTOR_EXTRACTORS:
        raise ValueError(f"Anomaly detection alerts aren't supported for {kind} insights")

    validator = _ALERT_CONFIG_VALIDATORS.get(config_type) if isinstance(config_type, str) else None
    if validator is None:
        raise ValueError(f"Unsupported alert config type: {config}")
    validator(
        _AlertConfigValidationContext(
            config=config if isinstance(config, dict) else {},
            query=query,
            query_kind=kind,
            parsed_condition=parsed_condition,
            threshold_config=threshold_config,
            require_threshold_bounds=require_threshold_bounds,
            detector_config=detector_config,
        )
    )
