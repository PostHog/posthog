from dataclasses import dataclass
from typing import Any

from posthog.schema import ActionsNode, EventsNode, ExperimentMeanMetric

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


def get_cuped_config(stats_config: dict | None, metric: object) -> CupedQueryConfig:
    if not isinstance(metric, ExperimentMeanMetric):
        return CupedQueryConfig()

    # Session property metrics use a separate session-deduplication CTE pipeline.
    # Keep CUPED disabled there until the same single-scan windowing is implemented.
    if isinstance(metric.source, (ActionsNode, EventsNode)) and is_session_property_metric(metric.source):
        return CupedQueryConfig()

    cuped_config = (stats_config or {}).get("cuped") or {}
    enabled = bool(cuped_config.get("enabled", False))
    if not enabled:
        return CupedQueryConfig()

    return CupedQueryConfig(
        enabled=True,
        lookback_days=_parse_lookback_days(cuped_config.get("lookback_days", DEFAULT_CUPED_LOOKBACK_DAYS)),
    )
