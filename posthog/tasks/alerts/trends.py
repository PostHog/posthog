from typing import Optional, cast

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight

from posthog.models import AlertConfiguration, Insight
from posthog.schema import (
    TrendsQuery,
    IntervalType,
    TrendsAlertConfig,
    InsightThreshold,
    AlertCondition,
    AlertConditionType,
    InsightsThresholdBounds,
    InsightThresholdType,
)
from posthog.caching.fetch_from_cache import InsightResult
from typing import TypedDict, NotRequired
from posthog.tasks.alerts.utils import (
    AlertEvaluationResult,
    NON_TIME_SERIES_DISPLAY_TYPES,
)


# TODO: move the TrendResult UI type to schema.ts and use that instead
class TrendResult(TypedDict):
    action: dict
    actions: list[dict]
    count: int
    data: list[float]
    days: list[str]
    dates: list[str]
    label: str
    labels: list[str]
    breakdown_value: str | int | list[str]
    aggregated_value: NotRequired[float]
    status: str | None
    compare_label: str | None
    compare: bool
    persons_urls: list[dict]
    persons: dict
    filter: dict


def check_trends_alert(alert: AlertConfiguration, insight: Insight, query: TrendsQuery) -> AlertEvaluationResult:
    if "type" in alert.config and alert.config["type"] == "TrendsAlertConfig":
        config = TrendsAlertConfig.model_validate(alert.config)
    else:
        ValueError(f"Unsupported alert config type: {alert.config}")

    condition = AlertCondition.model_validate(alert.condition)
    threshold = InsightThreshold.model_validate(alert.threshold.configuration) if alert.threshold else None

    match condition.type:
        case AlertConditionType.ABSOLUTE_VALUE:
            if threshold.type != InsightThresholdType.ABSOLUTE:
                raise ValueError(f"Absolute threshold not configured for alert condition ABSOLUTE_VALUE")

            # want value for current interval (last hour, last day, last week, last month)
            # depending on the alert calculation interval
            if _is_non_time_series_trend(query):
                filters_override = _date_range_override_for_alert(query, interval_negative_offset=0)
            else:
                # for non time series, it's an aggregated value for full interval
                # so we need to compute full insight
                filters_override = None

            calculation_result = calculate_for_query_based_insight(
                insight,
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                user=None,
                filters_override=filters_override,
            )

            if not calculation_result.result:
                raise RuntimeError(f"No results found for insight with alert id = {alert.id}")

            current_interval_value = _aggregate_trend_result_value(config, query, calculation_result)
            breaches = _validate_bounds(threshold.bounds, current_interval_value)

            return AlertEvaluationResult(value=current_interval_value, breaches=breaches)

        case AlertConditionType.RELATIVE_INCREASE:
            if _is_non_time_series_trend(query):
                raise ValueError(f"Relative alerts not supported for non time series trends")

            # to measure relative increase, we need to compute the trend value for the current interval
            # and check if it's currently already 'increased' above the trend for the previous interval

            filters_override_current_interval = _date_range_override_for_alert(query, interval_negative_offset=0)
            calculation_result = calculate_for_query_based_insight(
                insight,
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                user=None,
                filters_override=filters_override_current_interval,
            )
            current_interval_value = _aggregate_trend_result_value(config, query, calculation_result)

            filters_override_prev_interval = _date_range_override_for_alert(query, interval_negative_offset=1)
            calculation_result = calculate_for_query_based_insight(
                insight,
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                user=None,
                filters_override=filters_override_prev_interval,
            )
            prev_interval_value = _aggregate_trend_result_value(config, query, calculation_result)

            if threshold.type == InsightThresholdType.ABSOLUTE:
                value = current_interval_value - prev_interval_value
                breaches = _validate_bounds(threshold.bounds, current_interval_value)
            elif threshold.type == InsightThresholdType.PERCENTAGE:
                value = (current_interval_value - prev_interval_value) / prev_interval_value
                breaches = _validate_bounds(threshold.bounds, current_interval_value, is_percentage=True)
            else:
                raise ValueError(
                    f"Neither relative nor absolute threshold configured for alert condition RELATIVE_INCREASE"
                )

            return AlertEvaluationResult(value=value, breaches=breaches)

        case AlertConditionType.RELATIVE_DECREASE:
            if _is_non_time_series_trend(query):
                raise ValueError(f"Relative alerts not supported for non time series trends")

            # to measure relative decrease, we can't alert until current interval has completed
            # so we need to compute the trend value for the previous interval
            # and compare it with value for the interval before previous
            filters_override_prev_interval = _date_range_override_for_alert(query, interval_negative_offset=1)
            calculation_result = calculate_for_query_based_insight(
                insight,
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                user=None,
                filters_override=filters_override_prev_interval,
            )
            prev_interval_value = _aggregate_trend_result_value(config, query, calculation_result)

            filters_override_prev_prev_interval = _date_range_override_for_alert(query, interval_negative_offset=2)
            calculation_result = calculate_for_query_based_insight(
                insight,
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                user=None,
                filters_override=filters_override_prev_prev_interval,
            )
            prev_prev_interval_value = _aggregate_trend_result_value(config, query, calculation_result)

            if threshold.type == InsightThresholdType.ABSOLUTE:
                value = prev_interval_value - prev_prev_interval_value
                breaches = _validate_bounds(threshold.bounds, current_interval_value)
            elif threshold.type == InsightThresholdType.PERCENTAGE:
                value = (prev_interval_value - prev_prev_interval_value) / prev_prev_interval_value
                breaches = _validate_bounds(threshold.bounds, current_interval_value, is_percentage=True)
            else:
                raise ValueError(
                    f"Neither relative nor absolute threshold configured for alert condition RELATIVE_DECREASE"
                )

            return AlertEvaluationResult(value=value, breaches=breaches)

        case _:
            raise NotImplementedError(f"Unsupported alert condition type: {condition.type}")


def _is_non_time_series_trend(query: str) -> bool:
    return query.trendsFilter and query.trendsFilter.display in NON_TIME_SERIES_DISPLAY_TYPES


def _date_range_override_for_alert(query: TrendsQuery, interval_negative_offset: int) -> Optional[dict]:
    """
    interval_negative_offset = 0, return filters override for the current interval
    interval_negative_offset = -1, return filters override for the previous interval
    interval_negative_offset = -2, return filters override for the interval before previous 2
    ...
    """
    from_offset = interval_negative_offset or 1

    match query.interval:
        case IntervalType.DAY:
            date_from = f"-{from_offset}d"
            date_to = None if from_offset == 1 else f"-{from_offset - 1}d"
        case IntervalType.WEEK:
            date_from = f"-{from_offset}w"
            date_to = None if from_offset == 1 else f"-{from_offset - 1}w"
        case IntervalType.MONTH:
            date_from = f"-{from_offset}m"
            date_to = None if from_offset == 1 else f"-{from_offset - 1}m"
        case _:
            date_from = f"-{from_offset}h"
            date_to = None if from_offset == 1 else f"-{from_offset - 1}h"

    return {"date_from": date_from, "date_to": date_to}


def _aggregate_trend_result_value(config: TrendsAlertConfig, query: TrendsQuery, results: InsightResult) -> float:
    series_index = config.series_index
    result = cast(list[TrendResult], results.result)[series_index]

    if _is_non_time_series_trend(query):
        return result["aggregated_value"]

    return result["data"][-1]


def _validate_bounds(
    bounds: InsightsThresholdBounds, calculated_value: float, is_percentage: bool = False
) -> list[str]:
    formatted_value = f"{calculated_value:.2%}" if is_percentage else calculated_value

    if bounds.lower is not None and calculated_value < bounds.lower:
        lower_value = f"{bounds.lower:.2%}" if is_percentage else bounds.lower
        return [f"The trend value ({formatted_value}) is below the lower threshold ({lower_value})"]
    if bounds.upper is not None and calculated_value > bounds.upper:
        upper_value = f"{bounds.upper:.2%}" if is_percentage else bounds.upper
        return [f"The trend value ({formatted_value}) is above the upper threshold ({upper_value})"]

    return []
