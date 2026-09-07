from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, get_args

from prometheus_client import Counter, Histogram

from posthog.errors import QueryErrorCategory, classify_query_error

from .facade.enums import HOGQL_DEFINITION_KIND, MARKDOWN_DEFINITION_KIND, NODE_DEFINITION_KINDS

MetricRunOutcome = Literal[
    "success",
    "definition_error",
    "invalid_query",
    "rejected",
    "query_performance",
    "capacity",
    "cancelled",
    "concurrency_limited",
    "async_enqueued",
    "internal_error",
]

DefinitionKindLabel = Literal["hogql", "insight", "node", "markdown", "none"]

RelationshipProbeOutcome = Literal["ok", "join_invalid", "query_performance", "capacity", "cancelled", "error"]

METRIC_RUNS_COUNTER = Counter(
    "posthog_data_catalog_metric_runs_total",
    "Canonical metric runs, one per invocation. "
    "outcome is success (results returned, markdown metrics included); "
    "definition_error (the stored definition no longer runs — the table or column it names is gone); "
    "invalid_query (the engine rejected the prepared query, returned as 400); "
    "rejected (refused before execution: no definition, or a date override on a fixed-window metric); "
    "query_performance (the query hit a ClickHouse cost guardrail — timeout/memory/size/estimated-too-slow); "
    "capacity (shared ClickHouse pool momentarily saturated); "
    "cancelled (the caller dropped the query); "
    "concurrency_limited (denominator only — alert on posthog_clickhouse_query_concurrency_limit_exceeded); "
    "async_enqueued (a query status was returned to poll, not results — completion lands in the generic query series); "
    "or internal_error (unexpected system failure). "
    'Only internal_error is a system fault — alert on outcome="internal_error", and on the '
    "definition_error + invalid_query + internal_error ratio for catalog rot.",
    labelnames=["definition_kind", "outcome"],
)

METRIC_RUN_DURATION_SECONDS = Histogram(
    "posthog_data_catalog_metric_run_duration_seconds",
    "Blocking metric-run duration; only runs that returned results are observed (async enqueues excluded)",
    labelnames=["kind"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 45, 90, 180, 300, float("inf")),
)

RELATIONSHIP_PROBE_COUNTER = Counter(
    "posthog_data_catalog_relationship_probe_total",
    "Live join probes run while accepting a relationship proposal. "
    "outcome is ok; join_invalid (the proposed join does not work against the team's data, returned as 400); "
    "query_performance (the probe query hit a ClickHouse cost guardrail); "
    "capacity (shared ClickHouse pool momentarily saturated); cancelled (the caller dropped the query); "
    'or error (the probe itself broke). Only error is a system fault — alert on outcome="error", '
    "because no relationship can be accepted while the probe is broken.",
    labelnames=["outcome"],
)

# Both counters classify a query failure with the same function the query SLO path uses, so a
# ClickHouse cost guardrail or a saturated pool never reads as a broken definition or a broken probe.
_RUN_OUTCOME_BY_CATEGORY: dict[QueryErrorCategory, MetricRunOutcome] = {
    QueryErrorCategory.USER_ERROR: "definition_error",
    QueryErrorCategory.QUERY_PERFORMANCE_ERROR: "query_performance",
    QueryErrorCategory.RATE_LIMITED: "capacity",
    QueryErrorCategory.CANCELLED: "cancelled",
    QueryErrorCategory.ERROR: "internal_error",
}

_PROBE_OUTCOME_BY_CATEGORY: dict[QueryErrorCategory, RelationshipProbeOutcome] = {
    QueryErrorCategory.USER_ERROR: "join_invalid",
    QueryErrorCategory.QUERY_PERFORMANCE_ERROR: "query_performance",
    QueryErrorCategory.RATE_LIMITED: "capacity",
    QueryErrorCategory.CANCELLED: "cancelled",
    QueryErrorCategory.ERROR: "error",
}

for _kind in get_args(DefinitionKindLabel):
    METRIC_RUN_DURATION_SECONDS.labels(kind=_kind)
    for _outcome in get_args(MetricRunOutcome):
        METRIC_RUNS_COUNTER.labels(definition_kind=_kind, outcome=_outcome)

for _probe_outcome in get_args(RelationshipProbeOutcome):
    RELATIONSHIP_PROBE_COUNTER.labels(outcome=_probe_outcome)


def definition_kind_label(definition_kind: str | None) -> DefinitionKindLabel:
    if definition_kind is None:
        return "none"
    if definition_kind == HOGQL_DEFINITION_KIND:
        return "hogql"
    if definition_kind == MARKDOWN_DEFINITION_KIND:
        return "markdown"
    if definition_kind in NODE_DEFINITION_KINDS:
        return "node"
    return "insight"


class MetricRunRecorder:
    def __init__(self, kind: DefinitionKindLabel) -> None:
        self._kind = kind
        self._recorded = False

    def record(self, outcome: MetricRunOutcome) -> None:
        if self._recorded:
            return
        self._recorded = True
        METRIC_RUNS_COUNTER.labels(definition_kind=self._kind, outcome=outcome).inc()

    def observe_duration(self, seconds: float) -> None:
        METRIC_RUN_DURATION_SECONDS.labels(kind=self._kind).observe(seconds)


@contextmanager
def metric_run_outcome(definition_kind: str | None) -> Iterator[MetricRunRecorder]:
    """Record exactly one outcome per run: the first outcome claimed inside the block wins."""
    recorder = MetricRunRecorder(definition_kind_label(definition_kind))
    try:
        yield recorder
    except Exception:
        recorder.record("internal_error")
        raise
    else:
        recorder.record("success")


def metric_run_outcome_for(error: Exception) -> MetricRunOutcome:
    return _RUN_OUTCOME_BY_CATEGORY.get(classify_query_error(error), "internal_error")


def relationship_probe_outcome_for(error: Exception) -> RelationshipProbeOutcome:
    return _PROBE_OUTCOME_BY_CATEGORY.get(classify_query_error(error), "error")


def record_relationship_probe(outcome: RelationshipProbeOutcome) -> None:
    RELATIONSHIP_PROBE_COUNTER.labels(outcome=outcome).inc()
