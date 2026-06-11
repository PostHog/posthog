from typing import Any, cast

from posthog.schema import (
    AlertCondition,
    AlertConditionType,
    FunnelConversionMetric,
    FunnelsAlertConfig,
    FunnelsQuery,
    FunnelVizType,
)

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.event_usage import EventSource

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight

_FUNNEL_SUBJECT = "The funnel conversion rate"


class FunnelsExtractor:
    """Normalize a funnel insight into a single conversion-rate ``ComparableSeries`` (a percentage).

    A funnel STEPS result is a single snapshot (per breakdown), so there is no time axis: funnel
    alerts support only ``ABSOLUTE_VALUE`` conditions in v1 (relative change vs a prior window is a
    fast-follow). The config selects which step and how to measure conversion; the shared comparator
    then evaluates the resulting percentage against the threshold.
    """

    def extract(self, alert: AlertConfiguration, insight: Insight, query: Any) -> ExtractionResult:
        funnels_query = FunnelsQuery.model_validate(query)
        viz = funnels_query.funnelsFilter.funnelVizType if funnels_query.funnelsFilter else None
        if viz not in (None, FunnelVizType.STEPS):
            raise AlertExtractionError(
                f"Funnel alerts require a steps funnel, but this insight uses '{viz}'. "
                "Switch the funnel to the steps view to alert on conversion."
            )

        if not (alert.config and alert.config.get("type") == "FunnelsAlertConfig"):
            raise AlertExtractionError(f"Unsupported alert config type: {alert.config}")
        config = FunnelsAlertConfig.model_validate(alert.config)

        condition = AlertCondition.model_validate(alert.condition)
        if condition.type != AlertConditionType.ABSOLUTE_VALUE:
            raise AlertExtractionError("Funnel alerts only support absolute value conditions.")

        calculation_result = calculate_for_query_based_insight(
            insight,
            team=alert.team,
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            user=None,
            analytics_props={"source": EventSource.ALERT},
        )

        breakdowns = _steps_per_breakdown(calculation_result.result, alert)
        series = [
            ComparableSeries(
                label=_breakdown_label(steps),
                points=[SeriesPoint(date=None, value=_conversion_rate(steps, config))],
                current_index=0,
            )
            for steps in breakdowns
        ]
        return ExtractionResult(
            series=series,
            is_breakdown=len(breakdowns) > 1,
            subject=_FUNNEL_SUBJECT,
            framed=False,
        )


def _steps_per_breakdown(result: Any, alert: AlertConfiguration) -> list[list[dict[str, Any]]]:
    """Normalize the funnel result into a list of step-lists (one per breakdown value).

    A non-breakdown funnel returns ``list[step]``; a breakdown funnel returns ``list[list[step]]``.
    """
    # ``None`` means the query layer swallowed an error — raise (not AlertExtractionError) to avoid
    # a misfire, matching the trends/SQL extractors. An empty/wrong-shaped result is a config-level
    # "no data" case routed to the errored-alert path.
    if result is None:
        raise RuntimeError(f"No results found for insight with alert id = {alert.id}")
    if not result or not isinstance(result, list):
        raise AlertExtractionError("Funnel alert query returned no steps.")
    if isinstance(result[0], list):
        return cast(list[list[dict[str, Any]]], result)
    return [cast(list[dict[str, Any]], result)]


def _breakdown_label(steps: list[dict[str, Any]]) -> str:
    breakdown = steps[0].get("breakdown_value") if steps else None
    if breakdown is None:
        return "conversion"
    return ", ".join(str(v) for v in breakdown) if isinstance(breakdown, list) else str(breakdown)


def _conversion_rate(steps: list[dict[str, Any]], config: FunnelsAlertConfig) -> float:
    """Conversion rate (0–100) at the configured step.

    ``conversion_from_start`` divides by the first step's count (overall conversion to that step);
    ``conversion_from_previous`` divides by the prior step's count (step-over-step conversion).
    """
    step_count = len(steps)
    step_index = config.funnel_step if config.funnel_step is not None else step_count - 1
    if step_index < 0 or step_index >= step_count:
        raise AlertExtractionError(f"funnel_step {step_index} is out of range (funnel has {step_count} steps).")

    if config.metric == FunnelConversionMetric.CONVERSION_FROM_PREVIOUS:
        if step_index == 0:
            raise AlertExtractionError(
                "conversion_from_previous is undefined at the first step (there is no prior step); "
                "use conversion_from_start instead."
            )
        base_index = step_index - 1
    else:
        base_index = 0

    base = steps[base_index]["count"]
    if base == 0:
        return 0.0
    return steps[step_index]["count"] / base * 100
