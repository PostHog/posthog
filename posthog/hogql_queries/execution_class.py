from enum import StrEnum
from typing import TYPE_CHECKING, Any

import posthoganalytics

from posthog.clickhouse.workload import Workload
from posthog.scopes.catalog import APIScopeObject

if TYPE_CHECKING:
    from posthog.models.team import Team

TELEMETRY_CONCURRENCY_KEY_FLAG = "telemetry-concurrency-key"
LIVE_TELEMETRY_FLAG = "dashboard-live-telemetry"


class ExecutionClass(StrEnum):
    ANALYTICS = "analytics"
    METRICS = "telemetry_metrics"
    LOGS = "telemetry_logs"
    TRACES = "telemetry_traces"


# Telemetry queries run on their own ClickHouse clusters, so they take concurrency slots per cluster
# and leave the organization's analytics slots to the events cluster.
TELEMETRY_WORKLOAD: dict[ExecutionClass, Workload] = {
    ExecutionClass.METRICS: Workload.METRICS,
    ExecutionClass.LOGS: Workload.LOGS,
    ExecutionClass.TRACES: Workload.LOGS,
}

TELEMETRY_RESOURCE: dict[ExecutionClass, APIScopeObject] = {
    ExecutionClass.METRICS: "metrics",
    ExecutionClass.LOGS: "logs",
    ExecutionClass.TRACES: "tracing",
}

# How old a cached result a `refresh=live` request accepts. Metrics land in ClickHouse in 30 s blocks,
# so a fresher metrics read recomputes identical data. Analytics tiles keep their own staleness rules.
LIVE_CACHE_AGE_SECONDS: dict[ExecutionClass, int] = {
    ExecutionClass.METRICS: 30,
    ExecutionClass.LOGS: 5,
    ExecutionClass.TRACES: 5,
}

_KIND_TO_CLASS: dict[str, ExecutionClass] = {
    "MetricsQuery": ExecutionClass.METRICS,
    "MetricsHistogramQuery": ExecutionClass.METRICS,
    "LogsQuery": ExecutionClass.LOGS,
    "TraceSpansQuery": ExecutionClass.TRACES,
}

_WRAPPER_KINDS = frozenset({"InsightVizNode", "DataVisualizationNode", "DataTableNode"})


def execution_class_for_query(query: Any) -> ExecutionClass:
    if not isinstance(query, dict):
        return ExecutionClass.ANALYTICS
    if query.get("kind") in _WRAPPER_KINDS:
        query = query.get("source")
        if not isinstance(query, dict):
            return ExecutionClass.ANALYTICS
    return _KIND_TO_CLASS.get(str(query.get("kind")), ExecutionClass.ANALYTICS)


def team_flag_enabled_locally(team: "Team", flag_key: str) -> bool:
    # only_evaluate_locally keeps this flag check off the network - this runs on the query
    # hot path, so an inconclusive local evaluation must mean "off", never an HTTP call.
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag_key,
                str(team.uuid),
                groups={
                    "organization": str(team.organization_id),
                    "project": str(team.pk),
                },
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.pk)},
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False
