from dataclasses import dataclass
from typing import Any

from posthog.schema import (
    ActionsNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    StepOrderValue,
)

from posthog.hogql_queries.experiments.base_query_utils import is_session_property_metric

DEFAULT_CUPED_LOOKBACK_DAYS = 14
MIN_CUPED_LOOKBACK_DAYS = 1
MAX_CUPED_LOOKBACK_DAYS = 30


@dataclass(frozen=True)
class CupedQueryConfig:
    enabled: bool = False
    lookback_days: int = DEFAULT_CUPED_LOOKBACK_DAYS


def _parse_lookback_days(value: Any) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CUPED_LOOKBACK_DAYS

    if days < MIN_CUPED_LOOKBACK_DAYS:
        return MIN_CUPED_LOOKBACK_DAYS
    if days > MAX_CUPED_LOOKBACK_DAYS:
        return MAX_CUPED_LOOKBACK_DAYS
    return days


def _metric_supports_cuped(metric: object) -> bool:
    if isinstance(metric, ExperimentMeanMetric):
        # Session property metrics use a separate session-deduplication CTE pipeline.
        # Keep CUPED disabled there until the same single-scan windowing is implemented.
        if isinstance(metric.source, (ActionsNode, EventsNode)) and is_session_property_metric(metric.source):
            return False
        return True

    if isinstance(metric, ExperimentFunnelMetric):
        # Unordered funnels rely on a temporal join that excludes pre-exposure events,
        # which we'd need to relax (and re-mask) to compute the pre-window covariate.
        # Skip until that pattern is in place.
        if metric.funnel_order_type == StepOrderValue.UNORDERED:
            return False
        # Data warehouse funnel steps go through an unimplemented UNION ALL pattern;
        # CUPED can't be wired in until that exists.
        if any(isinstance(step, ExperimentDataWarehouseNode) for step in metric.series):
            return False
        return True

    return False


def get_cuped_config(stats_config: dict | None, metric: object) -> CupedQueryConfig:
    if not _metric_supports_cuped(metric):
        return CupedQueryConfig()

    cuped_config = (stats_config or {}).get("cuped") or {}
    enabled = bool(cuped_config.get("enabled", False))
    if not enabled:
        return CupedQueryConfig()

    return CupedQueryConfig(
        enabled=True,
        lookback_days=_parse_lookback_days(cuped_config.get("lookback_days", DEFAULT_CUPED_LOOKBACK_DAYS)),
    )
