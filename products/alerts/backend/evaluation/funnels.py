from typing import Any

from posthog.schema import AlertCondition, AlertConditionType, FunnelsAlertConfig, FunnelsQuery

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.event_usage import EventSource

from products.alerts.backend.evaluation.contract import AlertExtractionError, ExtractionResult
from products.alerts.backend.evaluation.funnel_strategies import strategy_for_viz
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


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

        calculation_result = calculate_for_query_based_insight(
            insight,
            team=alert.team,
            execution_mode=execution_mode,
            user=alert.created_by,
            analytics_props={"source": EventSource.ALERT},
        )

        # A None result means the query layer swallowed an error — surface it as RuntimeError (not
        # AlertExtractionError) so it routes to the harder failure path, matching the trends extractor
        # (and the shared error message the alert-failure dashboards bucket on).
        if calculation_result.result is None:
            raise RuntimeError(f"No results found for insight with alert id = {alert.id}")

        series = strategy.to_series(calculation_result.result, config, condition)
        return ExtractionResult(
            series=series,
            is_breakdown=len(series) > 1,
            subject=strategy.subject,
            framed=False,
            unit=strategy.unit,  # conversion rates are absolute 0–100 percentages
        )
