from typing import Any

from posthog.schema import AlertCondition, AlertConditionType, FunnelsAlertConfig, FunnelsQuery, IntervalType

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.event_usage import EventSource

from products.alerts.backend.evaluation.contract import AlertExtractionError, ExtractionResult, lookback_intervals_for
from products.alerts.backend.evaluation.funnel_strategies import strategy_for_viz
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


def _trailing_date_range_override(interval: IntervalType | None, periods: int) -> dict:
    # Widen the insight's date range to the last `periods` intervals (no date_to, so the current
    # interval is included) — mirrors the trends extractor so a relative funnel alert always has a
    # prior period to diff against, regardless of the insight's saved range.
    match interval:
        case IntervalType.DAY:
            unit = "d"
        case IntervalType.WEEK:
            unit = "w"
        case IntervalType.MONTH:
            unit = "m"
        case _:
            unit = "h"
    return {"date_from": f"-{periods}{unit}"}


class FunnelsExtractor:
    """Normalize a funnel insight into a ``ComparableSeries`` (one per breakdown) for the comparator.

    The shared scaffolding lives here — config/condition guards and running the query — while the
    viz-type-specific work (what metric to read, how to shape the result) is delegated to a
    ``FunnelVizStrategy`` selected by ``funnelVizType``. A breakdown funnel yields one series per
    breakdown value and fires if ANY breaches (matching trends).
    """

    def extract(
        self, alert: AlertConfiguration, insight: Insight, query: Any, execution_mode: ExecutionMode
    ) -> ExtractionResult:
        funnels_query = FunnelsQuery.model_validate(query)
        viz = funnels_query.funnelsFilter.funnelVizType if funnels_query.funnelsFilter else None
        strategy = strategy_for_viz(viz)

        if not (alert.config and alert.config.get("type") == "FunnelsAlertConfig"):
            raise AlertExtractionError(f"Unsupported alert config type: {alert.config}")
        config = FunnelsAlertConfig.model_validate(alert.config)

        condition = AlertCondition.model_validate(alert.condition)
        # Relative conditions need a prior value to compare against, which only a time-series viz
        # (historical trends) has — a steps snapshot is absolute-only.
        if condition.type != AlertConditionType.ABSOLUTE_VALUE and not strategy.supports_relative_conditions:
            raise AlertExtractionError("This funnel only supports absolute value conditions.")

        # A relative condition diffs against the prior period, but the insight's own date range may be
        # too short to yield one — leaving the alert silently inert. Widen it to the trailing intervals
        # the comparator needs (mirroring the trends extractor). Absolute conditions read the insight's
        # configured range as-is: a steps snapshot, or the trends last-complete period.
        filters_override = (
            None
            if condition.type == AlertConditionType.ABSOLUTE_VALUE
            else _trailing_date_range_override(funnels_query.interval, lookback_intervals_for(condition))
        )

        calculation_result = calculate_for_query_based_insight(
            insight,
            team=alert.team,
            execution_mode=execution_mode,
            user=alert.created_by,
            filters_override=filters_override,
            analytics_props={"source": EventSource.ALERT},
        )

        # A None result means the query layer swallowed an error — surface it as RuntimeError (not
        # AlertExtractionError) so it routes to the harder failure path, matching the trends extractor
        # (and the shared error message the alert-failure dashboards bucket on).
        if calculation_result.result is None:
            raise RuntimeError(f"No results found for insight with alert id = {alert.id}")

        series = strategy.to_series(calculation_result.result, config)
        return ExtractionResult(
            series=series,
            is_breakdown=len(series) > 1,
            subject=strategy.subject,
            framed=False,
            unit=strategy.unit,  # conversion rates are absolute 0–100 percentages
        )
