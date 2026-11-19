"""Where an endpoint's request time goes: its own service, the services it calls, and uninstrumented dependencies.

Reads a bounded sample of the endpoint's entry spans, loads the span tree under each one, and sums
every span's self-time (its duration minus the time its children cover) by the component it belongs
to. Descendants are clipped to their request's lifetime, so background work the endpoint never
waited on doesn't count. A client or producer span with no children is a call into something that sends no spans, such
as a database or a third-party API, so its time goes to that inferred dependency, named from the
span's peer attributes. Every other span's time goes to its own service.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from posthog.schema import HogQLQueryModifiers, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.enums import LabeledStrEnum
from posthog.models import Team

from products.apm.backend.logic.health.sources import (
    endpoint_expr,
    endpoint_span_names,
    environment_where,
    window_where,
)
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
    date_from: datetime, date_to: datetime, environment: str | None, service: str, endpoint: str
) -> ast.SelectQuery:
    # The same entry definition as the endpoints table, so the sample covers the row the user opened.
    query = parse_select(
        """
        SELECT trace_id, span_id, end_time
        FROM posthog.trace_spans
        WHERE {where} AND {env_where} AND service_name = {service} AND name IN {span_names} AND {endpoint_expr} = {endpoint}
            AND (is_root_span OR kind IN (2, 5))
        LIMIT {limit}
        """,
        placeholders={
            "where": window_where(date_from, date_to),
            "env_where": environment_where(environment),
            "service": ast.Constant(value=service),
            # The raw name check lets the name index skip other spans before the label is computed.
            "span_names": ast.Tuple(exprs=[ast.Constant(value=name) for name in endpoint_span_names(endpoint)]),
            "endpoint_expr": endpoint_expr(),
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


def _component_of(span: dict[str, Any], has_children: bool) -> tuple[str, TimeSpentComponentKind]:
    if span["kind"] in (CLIENT_KIND, PRODUCER_KIND) and not has_children and span["inferred_dependency"]:
        return span["inferred_dependency"], TimeSpentComponentKind.INFERRED
    return span["service_name"], TimeSpentComponentKind.SERVICE


def _clipped(span: dict[str, Any], start: datetime, end: datetime) -> dict[str, Any]:
    if span["timestamp"] >= start and span["end_time"] <= end:
        return span
    clipped_start, clipped_end = max(span["timestamp"], start), min(span["end_time"], end)
    duration_nano = max((clipped_end - clipped_start) // timedelta(microseconds=1) * 1000, 0)
    return {
        **span,
        "timestamp": clipped_start,
        "end_time": max(clipped_end, clipped_start),
        "duration_nano": duration_nano,
    }


def attribute_time_spent(spans: list[SpanRecord], entries: list[tuple[str, str]]) -> EndpointTimeSpentResult:
    """Sums self-time by component across the span tree under each entry span.

    `entries` are (trace_id, span_id) pairs. An entry missing from `spans` counts as no request, and so
    does one nested under another sampled entry, whose time the outer request already holds. Each span
    is attributed at most once, so the work stays linear in the spans even for cyclic parent links.
    """
    children: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_id: dict[tuple[str, str], dict[str, Any]] = {}
    for record in spans:
        span: dict[str, Any] = {
            "trace_id": record.trace_id,
            "span_id": record.span_id,
            # A span that names itself as parent is treated as a root, or it would cover its own time.
            "parent_span_id": "" if record.parent_span_id == record.span_id else record.parent_span_id,
            "service_name": record.service_name,
            "kind": record.kind,
            "timestamp": record.timestamp,
            "end_time": record.end_time,
            "duration_nano": record.duration_nano,
            "inferred_dependency": record.inferred_dependency,
        }
        by_id[(record.trace_id, record.span_id)] = span
        children[(record.trace_id, span["parent_span_id"])].append(span)

    # Outer requests first, so an entry nested inside another is claimed by it rather than split off.
    entry_spans = sorted(
        (span for span in (by_id.get(key) for key in dict.fromkeys(entries)) if span is not None),
        key=lambda span: (span["timestamp"], -span["duration_nano"]),
    )

    claimed: set[tuple[str, str]] = set()
    totals_nano: dict[tuple[str, TimeSpentComponentKind], int] = defaultdict(int)
    request_count = 0
    entry_duration_nano = 0
    for entry in entry_spans:
        trace_id = entry["trace_id"]
        if (trace_id, entry["span_id"]) in claimed:
            continue
        request_count += 1
        entry_duration_nano += entry["duration_nano"]
        claimed.add((trace_id, entry["span_id"]))
        subtree = [entry]
        index = 0
        while index < len(subtree):
            for child in children.get((trace_id, subtree[index]["span_id"]), []):
                if (trace_id, child["span_id"]) not in claimed:
                    claimed.add((trace_id, child["span_id"]))
                    subtree.append(child)
            index += 1
        clipped = [_clipped(span, entry["timestamp"], entry["end_time"]) for span in subtree]
        annotate_self_time(clipped)
        for span in clipped:
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
    *, team: Team, date_from: datetime, date_to: datetime, environment: str | None, service: str, endpoint: str
) -> EndpointTimeSpentResult:
    entry_rows = _run(team, _entry_spans_query(date_from, date_to, environment, service, endpoint))
    if not entry_rows:
        return EndpointTimeSpentResult(components=[], request_count=0, avg_duration_ms=None)
    entries = [(str(trace_id), str(span_id)) for trace_id, span_id, _ in entry_rows]
    trace_ids = sorted({trace_id for trace_id, _ in entries})
    # Descendants are clipped to their request, so the latest request end bounds the spans worth loading.
    spans_to = max(date_to, *(end_time for _, _, end_time in entry_rows))
    rows = _run(team, _trace_spans_query(date_from, spans_to, trace_ids))
    if len(rows) >= TIME_SPENT_SPAN_LIMIT:
        # Rows come ordered by trace, so only the last trace can be cut short. Dropping it keeps
        # missing children from turning into their parent's self-time.
        last_trace_id = rows[-1][0]
        rows = [row for row in rows if row[0] != last_trace_id]
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
        for row in rows
    ]
    return attribute_time_spent(spans, entries)
