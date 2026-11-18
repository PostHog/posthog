"""Reads who calls whom in a window, including dependencies that send no spans of their own.

A service edge is a server or consumer span whose parent span is in another service. An inferred
edge is a client or producer span with no child span, whose attributes name what it called: a peer
service, a database, a queue or a host. A target that is also a service with spans in the window
is left out, so an uninstrumented call into an instrumented service is not drawn twice.

Every edge is measured on the caller's side when the caller has a client or producer span, since
that is the latency and the errors the caller saw. Without one, the callee span is used.

Unlike the service map, this reads the whole window rather than a trace sample, so the counts add up
to the spans in the window. Fail-fast settings cap the bytes read and the run time instead.
"""

from dataclasses import dataclass
from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.apm.backend.logic.health.contract import DependencyEdge, DependencyKind
from products.apm.backend.logic.health.sources import environment_expr, window_where

DEPENDENCY_EDGES_LIMIT = 500
MAX_BYTES_TO_READ = 10_000_000_000
MAX_EXECUTION_SECONDS = 30

_ENTRY_KINDS = "(2, 5)"
# A left join leaves the callee columns null for a span with no matching child span.
# HogQL reads a null comparison as true, so the test goes through a function that maps null to false.
_HAS_CALLEE = "notEmpty(ifNull(c.service_name, ''))"
_CALL_KINDS = "(3, 4)"


def _attr(key: str) -> str:
    # HogQL returns null for a missing map key, and reads a null comparison as true, so every
    # attribute is read as a string with missing keys as empty.
    return f"ifNull(attributes['{key}'], '')"


def _has(key: str) -> str:
    return f"notEmpty({_attr(key)})"


def _suffix(key: str) -> str:
    return f"if({_has(key)}, concat(':', {_attr(key)}), '')"


# The first attribute that names the other end of a client or producer span, newest semantic
# conventions first. db.namespace replaced db.name; server.address replaced net.peer.name.
_TARGET = f"""multiIf(
    {_has("peer.service")}, {_attr("peer.service")},
    {_has("db.system")}, concat({_attr("db.system")}, if({_has("db.namespace")}, concat(':', {_attr("db.namespace")}), {_suffix("db.name")})),
    {_has("messaging.system")}, concat({_attr("messaging.system")}, {_suffix("messaging.destination.name")}),
    {_has("server.address")}, {_attr("server.address")},
    {_has("net.peer.name")}, {_attr("net.peer.name")},
    ''
)"""
_TARGET_KIND = f"""multiIf(
    {_has("peer.service")}, '{DependencyKind.SERVICE.value}',
    {_has("db.system")}, '{DependencyKind.DATABASE.value}',
    {_has("messaging.system")}, '{DependencyKind.QUEUE.value}',
    '{DependencyKind.EXTERNAL.value}'
)"""


@dataclass(frozen=True)
class DependenciesResult:
    edges: list[DependencyEdge]
    truncated: bool


def _dependencies_query(
    date_from: datetime, date_to: datetime, environment: str, service: str | None
) -> ast.SelectQuery:
    # The callee side is the right side of the join, so ClickHouse builds its hash table from entry
    # spans only, one per request, not from every span in the window.
    query = parse_select(
        f"""
        SELECT
            p.service_name AS caller,
            if({_HAS_CALLEE}, c.service_name, p.target) AS callee,
            if({_HAS_CALLEE}, 0, 1) AS inferred,
            if({_HAS_CALLEE}, '{DependencyKind.SERVICE.value}', p.target_kind) AS dependency_kind,
            count() AS requests,
            countIf(if(p.kind IN {_CALL_KINDS}, p.status_code, c.status_code) = 2) AS error_count,
            quantile(0.95)(if(p.kind IN {_CALL_KINDS}, p.duration_nano, c.duration_nano)) / 1e6 AS p95_ms
        FROM (
            SELECT trace_id, span_id, service_name, kind, status_code, duration_nano,
                {_TARGET} AS target, {_TARGET_KIND} AS target_kind
            FROM posthog.trace_spans
            WHERE {{where}} AND {{env_expr}} = {{environment}}
        ) AS p
        LEFT JOIN (
            SELECT trace_id, parent_span_id, service_name, status_code, duration_nano
            FROM posthog.trace_spans
            WHERE {{where}} AND {{env_expr}} = {{environment}} AND kind IN {_ENTRY_KINDS} AND NOT is_root_span
        ) AS c ON p.trace_id = c.trace_id AND p.span_id = c.parent_span_id
        WHERE if(
            {_HAS_CALLEE},
            c.service_name != p.service_name,
            p.kind IN {_CALL_KINDS}
            AND notEmpty(p.target)
            AND p.target NOT IN (
                SELECT service_name FROM posthog.trace_spans
                WHERE {{where}} AND {{env_expr}} = {{environment}}
                GROUP BY service_name
            )
        )
        GROUP BY caller, callee, inferred, dependency_kind
        HAVING {{service_where}}
        ORDER BY requests DESC, caller, callee
        LIMIT {{limit}}
        """,
        placeholders={
            "where": window_where(date_from, date_to),
            "env_expr": environment_expr(),
            "environment": ast.Constant(value=environment),
            "service_where": (
                parse_expr(
                    "caller = {service} OR callee = {service}", placeholders={"service": ast.Constant(value=service)}
                )
                if service
                else ast.Constant(value=True)
            ),
            "limit": ast.Constant(value=DEPENDENCY_EDGES_LIMIT + 1),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def get_dependencies(
    *, team: Team, date_from: datetime, date_to: datetime, environment: str, service: str | None = None
) -> DependenciesResult:
    rows = execute_hogql_query(
        query_type="ApmDependenciesQuery",
        query=_dependencies_query(date_from, date_to, environment, service),
        team=team,
        workload=Workload.LOGS,
        limit_context=LimitContext.QUERY,
        settings=HogQLGlobalSettings(
            max_execution_time=MAX_EXECUTION_SECONDS,
            max_bytes_to_read=MAX_BYTES_TO_READ,
            read_overflow_mode="throw",
        ),
    ).results
    edges = [
        DependencyEdge(
            caller=caller,
            callee=callee,
            inferred=bool(inferred),
            kind=DependencyKind(kind),
            requests=int(requests),
            error_count=int(error_count),
            p95_ms=float(p95_ms) if p95_ms is not None else None,
        )
        for caller, callee, inferred, kind, requests, error_count, p95_ms in rows[:DEPENDENCY_EDGES_LIMIT]
    ]
    return DependenciesResult(edges=edges, truncated=len(rows) > DEPENDENCY_EDGES_LIMIT)
