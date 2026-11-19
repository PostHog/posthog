"""Reads who calls whom in a window, including dependencies that send no spans of their own.

A service edge is a server or consumer span whose parent span is in another service. An inferred
edge is a client or producer span with no client, producer or entry child span, whose attributes name what it called: a peer
service, a database, a queue or a host. A call with no child whose target is a service with spans
in the window counts on that service's edge, so a call that never arrived still shows its failure.

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
from products.apm.backend.logic.health.sources import environment_where, window_where

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


# db.system.name replaced db.system, so the stable key wins when a span sends both.
_DB_SYSTEM = f"if({_has('db.system.name')}, {_attr('db.system.name')}, {_attr('db.system')})"

# The first attribute that names the other end of a client or producer span, newest semantic
# conventions first. db.namespace replaced db.name; server.address replaced net.peer.name.
_TARGET = f"""multiIf(
    {_has("peer.service")}, {_attr("peer.service")},
    notEmpty({_DB_SYSTEM}), concat({_DB_SYSTEM}, if({_has("db.namespace")}, concat(':', {_attr("db.namespace")}), {_suffix("db.name")})),
    {_has("messaging.system")}, concat({_attr("messaging.system")}, {_suffix("messaging.destination.name")}),
    {_has("server.address")}, {_attr("server.address")},
    {_has("net.peer.name")}, {_attr("net.peer.name")},
    ''
)"""
_TARGET_KIND = f"""multiIf(
    {_has("peer.service")}, '{DependencyKind.SERVICE.value}',
    notEmpty({_DB_SYSTEM}), '{DependencyKind.DATABASE.value}',
    {_has("messaging.system")}, '{DependencyKind.QUEUE.value}',
    '{DependencyKind.EXTERNAL.value}'
)"""


@dataclass(frozen=True)
class DependenciesResult:
    edges: list[DependencyEdge]
    truncated: bool


def _dependencies_query(
    date_from: datetime, date_to: datetime, environment: str | None, service: str | None
) -> ast.SelectQuery:
    # The callee side is the right side of the join, so ClickHouse builds its hash table from entry
    # spans only, one per request, not from every span in the window. A client span whose child call
    # has the same kind or reaches a service that the wrapper names is a wrapper, such as a retry around
    # the real call, and gets no edge of its own: the inner span already draws that dependency. A database
    # or queue span over an HTTP call that reaches no service keeps its edge, even when the child names a
    # host spelled like the database system. A leaf call whose target
    # is a service with spans in the window never reached it, say a timeout, and counts on that
    # service's edge rather than being dropped or drawn as a second, inferred node.
    reached = f"({_HAS_CALLEE} OR p.target_is_service)"
    query = parse_select(
        f"""
        SELECT
            p.service_name AS caller,
            if({_HAS_CALLEE}, c.service_name, p.target) AS callee,
            if({reached}, 0, 1) AS inferred,
            if({reached}, '{DependencyKind.SERVICE.value}', p.target_kind) AS dependency_kind,
            count() AS requests,
            countIf(if(p.kind IN {_CALL_KINDS}, p.status_code, c.status_code) = 2) AS error_count,
            quantile(0.95)(if(p.kind IN {_CALL_KINDS}, p.duration_nano, c.duration_nano)) / 1e6 AS p95_ms
        FROM (
            SELECT trace_id, span_id, service_name, kind, status_code, duration_nano,
                {_TARGET} AS target, {_TARGET_KIND} AS target_kind,
                target IN (
                    SELECT service_name FROM posthog.trace_spans
                    WHERE {{where}} AND {{env_where}} AND {{known_services_where}}
                    GROUP BY service_name
                ) AS target_is_service
            FROM posthog.trace_spans
            WHERE {{where}} AND {{env_where}} AND {{trace_where}}
        ) AS p
        LEFT JOIN (
            SELECT trace_id, parent_span_id, service_name, status_code, duration_nano
            FROM posthog.trace_spans
            WHERE {{where}} AND {{env_where}} AND {{trace_where}}
                AND kind IN {_ENTRY_KINDS} AND NOT is_root_span
        ) AS c ON p.trace_id = c.trace_id AND p.span_id = c.parent_span_id
        LEFT JOIN (
            SELECT
                x.trace_id AS trace_id,
                x.parent_span_id AS parent_span_id,
                groupUniqArray(x.target_kind) AS child_kinds,
                groupUniqArrayIf(e.service_name, notEmpty(ifNull(e.service_name, ''))) AS child_callees
            FROM (
                SELECT trace_id, span_id, parent_span_id, {_TARGET} AS target, {_TARGET_KIND} AS target_kind
                FROM posthog.trace_spans
                WHERE {{where}} AND {{env_where}} AND {{trace_where}}
                    AND kind IN {_CALL_KINDS} AND NOT is_root_span
            ) AS x
            LEFT JOIN (
                SELECT trace_id, parent_span_id, service_name
                FROM posthog.trace_spans
                WHERE {{where}} AND {{env_where}} AND {{trace_where}}
                    AND kind IN {_ENTRY_KINDS} AND NOT is_root_span
            ) AS e ON x.trace_id = e.trace_id AND x.span_id = e.parent_span_id
            GROUP BY x.trace_id, x.parent_span_id
        ) AS cc ON p.trace_id = cc.trace_id AND p.span_id = cc.parent_span_id
        WHERE if(
            {_HAS_CALLEE},
            c.service_name != p.service_name,
            p.kind IN {_CALL_KINDS}
            AND NOT has(cc.child_kinds, p.target_kind)
            AND NOT has(cc.child_callees, p.target)
            AND notEmpty(p.target)
            AND p.target != p.service_name
        )
        GROUP BY caller, callee, inferred, dependency_kind
        HAVING {{service_where}}
        ORDER BY requests DESC, caller, callee
        LIMIT {{limit}}
        """,
        placeholders={
            "where": window_where(date_from, date_to),
            "env_where": environment_where(environment),
            "trace_where": _service_traces_where(date_from, date_to, environment, service),
            "known_services_where": _known_services_where(date_from, date_to, environment, service),
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


def _service_traces_where(
    date_from: datetime, date_to: datetime, environment: str | None, service: str | None
) -> ast.Expr:
    # Every edge on a service, in either direction, sits in a trace that has a span from it or a call
    # span that names it: a call that never reached the service, or one to a service that sends no
    # spans. The scans and the join then see only those traces instead of the whole environment.
    if not service:
        return ast.Constant(value=True)
    return parse_expr(
        f"""trace_id IN (
            SELECT trace_id FROM posthog.trace_spans
            WHERE {{where}} AND {{env_where}}
                AND (service_name = {{service}} OR (kind IN {_CALL_KINDS} AND {_TARGET} = {{service}}))
        )""",
        placeholders={
            "where": window_where(date_from, date_to),
            "env_where": environment_where(environment),
            "service": ast.Constant(value=service),
        },
    )


def _known_services_where(
    date_from: datetime, date_to: datetime, environment: str | None, service: str | None
) -> ast.Expr:
    # Only the targets named by calls in the selected traces need checking. service_name follows
    # time_bucket in the sort key, so checking those names reads their granules, not the whole window.
    if not service:
        return ast.Constant(value=True)
    return parse_expr(
        f"""service_name IN (
            SELECT {_TARGET} FROM posthog.trace_spans
            WHERE {{where}} AND {{env_where}} AND {{trace_where}} AND kind IN {_CALL_KINDS}
        )""",
        placeholders={
            "where": window_where(date_from, date_to),
            "env_where": environment_where(environment),
            "trace_where": _service_traces_where(date_from, date_to, environment, service),
        },
    )


def get_dependencies(
    *, team: Team, date_from: datetime, date_to: datetime, environment: str | None, service: str | None = None
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
