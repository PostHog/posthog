"""Where an endpoint's request time goes: its own service, the services it calls, and uninstrumented dependencies.

Reads a bounded sample of the endpoint's entry spans, loads the span tree under each one, and sums
every span's self-time (its duration minus the time its children cover) by the component it belongs
to. A client or producer span with no children is a call into something that sends no spans, such
as a database or a third-party API, so its time goes to that inferred dependency, named from the
span's peer attributes. Every other span's time goes to its own service.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from posthog.schema import HogQLQueryModifiers, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.enums import LabeledStrEnum
from posthog.models import Team

from products.apm.backend.logic.health.sources import environment_expr, window_where
from products.tracing.backend.facade.api import annotate_self_time

TIME_SPENT_REQUEST_LIMIT = 200
# Caps the spans loaded for the sampled requests, however deep their trees are.
TIME_SPENT_SPAN_LIMIT = 100_000
# Components past this many fold into one "Other" row, so a fan-out to many hosts stays readable.
TIME_SPENT_COMPONENT_LIMIT = 8
OTHER_COMPONENT = "Other"

CLIENT_KIND = 3
PRODUCER_KIND = 4

# Checked in order: the first non-empty one names the dependency a leaf client span calls.
INFERRED_DEPENDENCY_ATTRIBUTES = (
    "peer.service",
    "db.system.name",
    "db.system",
    "messaging.system",
    "server.address",
    "net.peer.name",
)


class TimeSpentComponentKind(LabeledStrEnum):
    SERVICE = "service"
    INFERRED = "inferred"
    OTHER = "other"


@dataclass(frozen=True)
class TimeSpentComponent:
    name: str
    kind: TimeSpentComponentKind
    total_ms: float
    avg_ms_per_request: float
    share: float


@dataclass(frozen=True)
class EndpointTimeSpentResult:
    components: list[TimeSpentComponent]
    request_count: int
    avg_duration_ms: float | None


@dataclass(frozen=True)
class SpanRecord:
    trace_id: str
    span_id: str
    parent_span_id: str
    service_name: str
    kind: int
    timestamp: datetime
    end_time: datetime
    duration_nano: int
    inferred_dependency: str | None


def _inferred_dependency_expr() -> ast.Expr:
    # Span attributes live in the typed str map, so each read carries the `__str` suffix.
    reads: list[ast.Expr] = [
        ast.Call(
            name="nullIf",
            args=[ast.Field(chain=["attributes", f"{key}__str"]), ast.Constant(value="")],
        )
        for key in INFERRED_DEPENDENCY_ATTRIBUTES
    ]
    return ast.Call(name="coalesce", args=reads)


def _entry_spans_query(
    date_from: datetime, date_to: datetime, environment: str, service: str, endpoint: str
) -> ast.SelectQuery:
    # The same entry definition as the endpoints table, so the sample covers the row the user opened.
    query = parse_select(
        """
        SELECT trace_id, span_id
        FROM posthog.trace_spans
        WHERE {where} AND {env_expr} = {environment} AND service_name = {service} AND name = {endpoint}
            AND (is_root_span OR kind IN (2, 5))
        LIMIT {limit}
        """,
        placeholders={
            "where": window_where(date_from, date_to),
            "env_expr": environment_expr(),
            "environment": ast.Constant(value=environment),
            "service": ast.Constant(value=service),
            "endpoint": ast.Constant(value=endpoint),
            "limit": ast.Constant(value=TIME_SPENT_REQUEST_LIMIT),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _trace_spans_query(date_from: datetime, date_to: datetime, trace_ids: list[str]) -> ast.SelectQuery:
    # Downstream spans count whatever environment they report, since the request waits on them all.
    query = parse_select(
        """
        SELECT trace_id, span_id, parent_span_id, service_name, kind, timestamp, end_time, duration_nano,
            if(kind IN (3, 4), {inferred}, NULL)
        FROM posthog.trace_spans
        WHERE {where} AND trace_id IN {trace_ids}
        ORDER BY trace_id, span_id
        LIMIT {span_limit}
        """,
        placeholders={
            "where": window_where(date_from, date_to),
            "inferred": _inferred_dependency_expr(),
            "trace_ids": ast.Tuple(exprs=[ast.Constant(value=trace_id) for trace_id in trace_ids]),
            "span_limit": ast.Constant(value=TIME_SPENT_SPAN_LIMIT),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _run(team: Team, query: ast.SelectQuery) -> list:
    return execute_hogql_query(
        query_type="ApmEndpointTimeSpentQuery",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=HogQLGlobalSettings(max_execution_time=30),
        modifiers=HogQLQueryModifiers(propertyGroupsMode=PropertyGroupsMode.OPTIMIZED),
    ).results


def _component_of(span: dict, has_children: bool) -> tuple[str, TimeSpentComponentKind]:
    if span["kind"] in (CLIENT_KIND, PRODUCER_KIND) and not has_children and span["inferred_dependency"]:
        return span["inferred_dependency"], TimeSpentComponentKind.INFERRED
    return span["service_name"], TimeSpentComponentKind.SERVICE


def attribute_time_spent(spans: list[SpanRecord], entries: list[tuple[str, str]]) -> EndpointTimeSpentResult:
    """Sums self-time by component across the span tree under each entry span.

    `entries` are (trace_id, span_id) pairs. An entry missing from `spans` counts as no request.
    """
    children: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_id: dict[tuple[str, str], dict] = {}
    for record in spans:
        span = {
            "trace_id": record.trace_id,
            "span_id": record.span_id,
            "parent_span_id": record.parent_span_id,
            "service_name": record.service_name,
            "kind": record.kind,
            "timestamp": record.timestamp,
            "end_time": record.end_time,
            "duration_nano": record.duration_nano,
            "inferred_dependency": record.inferred_dependency,
        }
        by_id[(record.trace_id, record.span_id)] = span
        children[(record.trace_id, record.parent_span_id)].append(span)

    totals_nano: dict[tuple[str, TimeSpentComponentKind], int] = defaultdict(int)
    request_count = 0
    entry_duration_nano = 0
    for trace_id, span_id in entries:
        entry = by_id.get((trace_id, span_id))
        if entry is None:
            continue
        request_count += 1
        entry_duration_nano += entry["duration_nano"]
        subtree = [entry]
        index = 0
        while index < len(subtree):
            subtree.extend(children.get((trace_id, subtree[index]["span_id"]), []))
            index += 1
        annotate_self_time(subtree)
        for span in subtree:
            has_children = bool(children.get((trace_id, span["span_id"])))
            totals_nano[_component_of(span, has_children)] += span["self_time_nano"]

    attributed_nano = sum(totals_nano.values())
    if request_count == 0 or attributed_nano == 0:
        return EndpointTimeSpentResult(
            components=[],
            request_count=request_count,
            avg_duration_ms=entry_duration_nano / request_count / 1e6 if request_count else None,
        )

    ranked = sorted(totals_nano.items(), key=lambda item: (-item[1], item[0][0]))
    if len(ranked) > TIME_SPENT_COMPONENT_LIMIT:
        rest = sum(nano for _, nano in ranked[TIME_SPENT_COMPONENT_LIMIT - 1 :])
        ranked = [*ranked[: TIME_SPENT_COMPONENT_LIMIT - 1], ((OTHER_COMPONENT, TimeSpentComponentKind.OTHER), rest)]

    components = [
        TimeSpentComponent(
            name=name,
            kind=kind,
            total_ms=nano / 1e6,
            avg_ms_per_request=nano / request_count / 1e6,
            share=nano / attributed_nano,
        )
        for (name, kind), nano in ranked
    ]
    return EndpointTimeSpentResult(
        components=components,
        request_count=request_count,
        avg_duration_ms=entry_duration_nano / request_count / 1e6,
    )


def get_endpoint_time_spent(
    *, team: Team, date_from: datetime, date_to: datetime, environment: str, service: str, endpoint: str
) -> EndpointTimeSpentResult:
    entries = [
        (str(trace_id), str(span_id))
        for trace_id, span_id in _run(team, _entry_spans_query(date_from, date_to, environment, service, endpoint))
    ]
    if not entries:
        return EndpointTimeSpentResult(components=[], request_count=0, avg_duration_ms=None)
    trace_ids = sorted({trace_id for trace_id, _ in entries})
    spans = [
        SpanRecord(
            trace_id=row[0],
            span_id=row[1],
            parent_span_id=row[2],
            service_name=row[3],
            kind=int(row[4]),
            timestamp=row[5],
            end_time=row[6],
            duration_nano=int(row[7]),
            inferred_dependency=row[8],
        )
        for row in _run(team, _trace_spans_query(date_from, date_to, trace_ids))
    ]
    return attribute_time_spent(spans, entries)
