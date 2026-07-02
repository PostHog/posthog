from collections.abc import Callable
from typing import Any, cast

from posthog.schema import (
    AlertCondition,
    AlertConditionType,
    InsightThreshold,
    InsightThresholdType,
    IntervalType,
    TrendsAlertConfig,
    TrendsQuery,
)

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.caching.fetch_from_cache import InsightResult
from posthog.event_usage import EventSource

# These helpers also back the anomaly detector, so they remain in the tasks module for now.
from posthog.tasks.alerts.trends import (
    _date_range_override_for_intervals,
    _has_breakdown,
    _is_non_time_series_trend,
    _pick_series_result,
)

from products.alerts.backend.evaluation.contract import (
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
    lookback_intervals_for,
    zero_sentinel_series,
)
from products.alerts.backend.evaluation.formatting import humanize_breakdown_label, make_trends_value_formatter
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


class TrendsExtractor:
    """Execute a trends insight and normalize the result into ``ComparableSeries``.

    Owns the trends-specific decisions — series/breakdown picking, how many intervals to
    fetch per condition, and which interval is the comparison anchor (the "wait for the
    current interval to complete" policy) — and hides them behind the contract. The
    comparator then interprets the series without knowing it came from a trend.

    Execution order per condition is significant and must hold: pre-execution config guards,
    run the query, handle empty/None results, post-execution ongoing-interval guard, then
    normalize. Relative conditions are invalid for non-time-series insights and raise.
    """

    def extract(
        self, alert: AlertConfiguration, insight: Insight, query: Any, execution_mode: ExecutionMode
    ) -> ExtractionResult:
        query = TrendsQuery.model_validate(query)
        if not (alert.config and "type" in alert.config and alert.config["type"] == "TrendsAlertConfig"):
            raise ValueError(f"Unsupported alert config type: {alert.config}")
        config = TrendsAlertConfig.model_validate(alert.config)
        condition = AlertCondition.model_validate(alert.condition)
        # Dispatcher short-circuits when threshold/bounds are missing, so both are present here.
        if alert.threshold is None:
            raise ValueError("TrendsExtractor requires a threshold — dispatcher invariant violated")
        threshold = InsightThreshold.model_validate(alert.threshold.configuration)
        if threshold.bounds is None:
            raise ValueError("TrendsExtractor requires threshold bounds — dispatcher invariant violated")

        # Render breach values the way the insight displays them (currency, prefix/postfix, decimals).
        value_formatter = make_trends_value_formatter(query.trendsFilter, alert.team.base_currency)

        is_non_time_series = _is_non_time_series_trend(query)
        has_breakdown = _has_breakdown(query)
        check_current_interval = bool(config.check_ongoing_interval)
        lookback_intervals = lookback_intervals_for(condition)
        interval_type = None if is_non_time_series else query.interval

        match condition.type:
            case AlertConditionType.ABSOLUTE_VALUE:
                if threshold.type != InsightThresholdType.ABSOLUTE:
                    raise ValueError("Absolute threshold not configured for alert condition ABSOLUTE_VALUE")
                # Non-time-series aggregates over the full interval; time-series looks back N intervals.
                filters_override = (
                    None
                    if is_non_time_series
                    else _date_range_override_for_intervals(query, last_x_intervals=lookback_intervals)
                )
                calculation_result = self._calculate(alert, insight, execution_mode, filters_override)
                if (
                    empty := self._empty_result(
                        calculation_result, alert, has_breakdown, interval_type, value_formatter
                    )
                ) is not None:
                    return empty
                if check_current_interval and threshold.bounds.upper is None:
                    raise ValueError(
                        "check_ongoing_interval is only supported for alert condition ABSOLUTE_VALUE when upper threshold is specified"
                    )
                anchor_is_current = check_current_interval or is_non_time_series

            case AlertConditionType.RELATIVE_INCREASE:
                if is_non_time_series:
                    raise ValueError("Relative alerts not supported for non time series trends")
                # When the current interval is incomplete we compare the previous interval
                # against the one before it, so we need the extra lookback interval.
                filters_override = _date_range_override_for_intervals(query, last_x_intervals=lookback_intervals)
                calculation_result = self._calculate(alert, insight, execution_mode, filters_override)
                if (
                    empty := self._empty_result(
                        calculation_result, alert, has_breakdown, interval_type, value_formatter
                    )
                ) is not None:
                    return empty
                if check_current_interval and threshold.bounds.upper is None:
                    raise ValueError(
                        "check_ongoing_interval is only supported for alert condition RELATIVE_INCREASE when upper threshold is specified"
                    )
                anchor_is_current = check_current_interval

            case AlertConditionType.RELATIVE_DECREASE:
                if is_non_time_series:
                    raise ValueError("Relative alerts not supported for non time series trends")
                filters_override = _date_range_override_for_intervals(query, last_x_intervals=lookback_intervals)
                calculation_result = self._calculate(alert, insight, execution_mode, filters_override)
                if (
                    empty := self._empty_result(
                        calculation_result, alert, has_breakdown, interval_type, value_formatter
                    )
                ) is not None:
                    return empty
                anchor_is_current = False

            case _:
                raise NotImplementedError(f"Unsupported alert condition type: {condition.type}")

        series = self._to_series(config, calculation_result, has_breakdown, is_non_time_series, anchor_is_current)
        # subject/framed use the ExtractionResult defaults ("The insight value", framed).
        return ExtractionResult(
            series=series,
            is_breakdown=has_breakdown,
            interval_type=interval_type,
            value_formatter=value_formatter,
        )

    def _calculate(
        self,
        alert: AlertConfiguration,
        insight: Insight,
        execution_mode: ExecutionMode,
        filters_override: dict | None,
    ) -> InsightResult:
        return calculate_for_query_based_insight(
            insight,
            team=alert.team,
            execution_mode=execution_mode,
            # Scheduled alert check (no request user); attribute the read to the alert owner so
            # warehouse HogQL access control resolves against their access.
            user=alert.created_by,
            filters_override=filters_override,
            analytics_props={"source": EventSource.ALERT},
        )

    def _empty_result(
        self,
        calculation_result: InsightResult,
        alert: AlertConfiguration,
        has_breakdown: bool,
        interval_type: IntervalType | None,
        value_formatter: Callable[[float], str],
    ) -> ExtractionResult | None:
        """A ``None`` result means the query layer swallowed an error — raise to avoid a misfire.
        An empty result means no data, treated as a 0 value compared against the threshold (this
        can fire a breach, e.g. a lower-bound alert)."""
        if calculation_result.result is None:
            raise RuntimeError(f"No results found for insight with alert id = {alert.id}")
        if not calculation_result.result:
            return ExtractionResult(
                series=[zero_sentinel_series()],
                is_breakdown=has_breakdown,
                interval_type=interval_type,
                empty_query_result=True,
                value_formatter=value_formatter,
            )
        return None

    def _to_series(
        self,
        config: TrendsAlertConfig,
        calculation_result: InsightResult,
        has_breakdown: bool,
        is_non_time_series: bool,
        anchor_is_current: bool,
    ) -> list[ComparableSeries]:
        if has_breakdown:
            results = cast(list[dict[str, Any]], calculation_result.result)
        else:
            results = [cast(dict[str, Any], _pick_series_result(config, calculation_result))]

        series: list[ComparableSeries] = []
        for result in results:
            if is_non_time_series:
                points = [SeriesPoint(date=None, value=result["aggregated_value"])]
            else:
                data = result["data"]
                dates = result.get("dates") or result.get("days") or [None] * len(data)
                points = [SeriesPoint(date=date, value=value) for date, value in zip(dates, data)]

            # Anchor on the current (ongoing) interval, or the last complete one. On a series
            # shorter than expected this can go negative and wrap, which the comparator then
            # treats as having no previous point — acceptable for a degenerate sparse series.
            current_index = len(points) - 1 if anchor_is_current else len(points) - 2
            series.append(
                ComparableSeries(
                    label=humanize_breakdown_label(result["label"]),
                    points=points,
                    current_index=current_index,
                    is_current_interval=anchor_is_current,
                )
            )
        return series
