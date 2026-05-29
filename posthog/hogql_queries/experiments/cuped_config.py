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


def _parse_lookback_days(value: Any, fallback: int = DEFAULT_CUPED_LOOKBACK_DAYS) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return fallback

    if days < MIN_CUPED_LOOKBACK_DAYS:
        return MIN_CUPED_LOOKBACK_DAYS
    if days > MAX_CUPED_LOOKBACK_DAYS:
        return MAX_CUPED_LOOKBACK_DAYS
    return days


def _resolve_lookback_days(experiment_value: Any, team_default: Any) -> int:
    """Resolve lookback days using precedence: experiment value > team default > hardcoded default.

    Invalid values at either level fall through to the next level rather than failing.
    """
    team_fallback = _parse_lookback_days(team_default) if team_default is not None else DEFAULT_CUPED_LOOKBACK_DAYS
    if experiment_value is None:
        return team_fallback
    return _parse_lookback_days(experiment_value, fallback=team_fallback)


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


def get_cuped_config(
    stats_config: dict | None,
    metric: object,
    team_default_enabled: bool = False,
    team_default_lookback_days: int | None = None,
) -> CupedQueryConfig:
    if not _metric_supports_cuped(metric):
        return CupedQueryConfig()

    cuped_config = (stats_config or {}).get("cuped") or {}
    # Distinguish "experiment hasn't set this" from "experiment explicitly disabled it":
    # only the latter should override a team default of `True`.
    if "enabled" in cuped_config:
        enabled = bool(cuped_config["enabled"])
    else:
        enabled = team_default_enabled

    if not enabled:
        return CupedQueryConfig()

    return CupedQueryConfig(
        enabled=True,
        lookback_days=_resolve_lookback_days(cuped_config.get("lookback_days"), team_default_lookback_days),
    )
