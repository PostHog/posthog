"""Reads the health row for every service in a window from the spans table.

A service's request rate comes from its entry spans: server spans and consumer spans. A service
that emits neither, such as a scheduled job, falls back to its root spans so it still gets a row.
The environment is the first non-empty resource attribute in the resolution order below, with the
cluster name as the last fallback and `default` when nothing is set.
"""

from dataclasses import dataclass
from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.apm.backend.logic.health.contract import (
    EndpointHealth,
    HealthRow,
    ServiceEdge,
    ServiceHealth,
    rank_endpoints,
    rank_services,
)

SPARKLINE_POINTS = 24
SERVICES_LIMIT = 500
ENDPOINTS_LIMIT = 500
# The map joins spans to their parents, so it reads a bounded sample of traces, not the whole window.
MAP_TRACE_LIMIT = 2000
MAP_EDGES_LIMIT = 1000
# Caps the rows the self-join holds in memory, however many spans the sampled traces carry.
MAP_SPAN_LIMIT = 200_000
DEFAULT_ENVIRONMENT = "default"

ENVIRONMENT_ATTRIBUTES = (
    "deployment.environment.name",
    "deployment.environment",
    "env",
    "k8s.cluster.name",
)

# Mirrors products/tracing/backend/logic.py's TIME_BUCKET_DATE_RANGE_WHERE: time_bucket is a
# materialized, coarse truncation of timestamp and leads trace_spans' primary key, so a day-bound
# predicate on it adds no rows but lets ClickHouse prune parts instead of scanning every part the
# team has. Pinned to UTC so a non-UTC day boundary can't drop same-day rows.
_TIME_BUCKET_DATE_RANGE_WHERE = (
    "toStartOfDay(time_bucket, 'UTC') >= toStartOfDay({date_from}, 'UTC') "
    "AND toStartOfDay(time_bucket, 'UTC') <= toStartOfDay({date_to}, 'UTC')"
)


@dataclass(frozen=True)
class ServicesHealthResult:
    services: list[ServiceHealth]
    environments: list[str]


@dataclass(frozen=True)
class ServiceMapResult:
    edges: list[ServiceEdge]
    trace_count: int


def environment_expr() -> ast.Expr:
    parts = ", ".join(f"nullIf(resource_attributes['{key}'], '')" for key in ENVIRONMENT_ATTRIBUTES)
    return parse_expr(
        f"coalesce({parts}, {{default}})", placeholders={"default": ast.Constant(value=DEFAULT_ENVIRONMENT)}
    )


def _window_where(date_from: datetime, date_to: datetime) -> ast.Expr:
    return parse_expr(
        f"timestamp >= {{date_from}} AND timestamp < {{date_to}} AND {_TIME_BUCKET_DATE_RANGE_WHERE}",
        placeholders={"date_from": ast.Constant(value=date_from), "date_to": ast.Constant(value=date_to)},
    )


def _services_query(date_from: datetime, date_to: datetime, environment: str) -> ast.SelectQuery:
    # Server and consumer spans are the request count. Root spans are the fallback for services with
    # neither, so a job's client spans count once each rather than once per downstream call.
    #
    # A team with more services than SERVICES_LIMIT needs the worst ones to survive the cutoff, so
    # the ranking (error rate, then error count, then name — the same order rank_services applies)
    # runs in SQL before LIMIT, not after. The HAVING also drops services with no counted spans,
    # which would otherwise waste a LIMIT slot ahead of a service that actually has traffic.
    query = parse_select(
        """
        SELECT
            service_name,
            countIf(kind IN (2, 5)) AS entry_spans,
            if(countIf(kind IN (2, 5)) > 0, countIf(kind IN (2, 5)), countIf(is_root_span)) AS span_count,
            if(countIf(kind IN (2, 5)) > 0, countIf(kind IN (2, 5) AND status_code = 2), countIf(is_root_span AND status_code = 2)) AS error_count,
            if(countIf(kind IN (2, 5)) > 0,
               quantileIf(0.95)(duration_nano, kind IN (2, 5)),
               quantileIf(0.95)(duration_nano, is_root_span)) / 1e6 AS p95_ms
        FROM posthog.trace_spans
        WHERE {where} AND {env_expr} = {environment}
        GROUP BY service_name
        HAVING span_count > 0
        ORDER BY error_count / span_count DESC, error_count DESC, service_name
        LIMIT {limit}
        """,
        placeholders={
            "where": _window_where(date_from, date_to),
            "env_expr": environment_expr(),
            "environment": ast.Constant(value=environment),
            "limit": ast.Constant(value=SERVICES_LIMIT),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _endpoints_query(date_from: datetime, date_to: datetime, environment: str, service: str | None) -> ast.SelectQuery:
    # An endpoint is an entry span name: what a server or consumer span handles, or what a root span
    # starts (a job with no server spans). This is the entry definition the Tracing service health
    # view uses, so a worker's job shows up here the same way it gets a row on the services tab.
    query = parse_select(
        """
        SELECT
            service_name,
            name,
            count() AS span_count,
            countIf(status_code = 2) AS error_count,
            quantile(0.95)(duration_nano) / 1e6 AS p95_ms
        FROM posthog.trace_spans
        WHERE {where} AND {env_expr} = {environment} AND {service_where} AND (is_root_span OR kind IN (2, 5))
        GROUP BY service_name, name
        ORDER BY error_count / span_count DESC, error_count DESC, service_name, name
        LIMIT {limit}
        """,
        placeholders={
            "where": _window_where(date_from, date_to),
            "env_expr": environment_expr(),
            "environment": ast.Constant(value=environment),
            "service_where": (
                parse_expr("service_name = {service}", placeholders={"service": ast.Constant(value=service)})
                if service
                else ast.Constant(value=True)
            ),
            "limit": ast.Constant(value=ENDPOINTS_LIMIT),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _sampled_traces_query(date_from: datetime, date_to: datetime, environment: str) -> ast.SelectQuery:
    # DISTINCT with LIMIT stops reading once it has enough trace IDs, where GROUP BY would first
    # aggregate every trace in the window.
    query = parse_select(
        """
        SELECT DISTINCT trace_id
        FROM posthog.trace_spans
        WHERE {where} AND {env_expr} = {environment}
        LIMIT {limit}
        """,
        placeholders={
            "where": _window_where(date_from, date_to),
            "env_expr": environment_expr(),
            "environment": ast.Constant(value=environment),
            "limit": ast.Constant(value=MAP_TRACE_LIMIT),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _service_edges_query(
    date_from: datetime, date_to: datetime, environment: str, trace_ids: list[str]
) -> ast.SelectQuery:
    # A call shows up as a callee span whose parent span belongs to another service, so each call
    # counts once however many client spans the caller wraps around it. Both ends must be in the
    # environment: a sampled trace can also hold spans from another environment. The CTE is read once
    # per side of the join, so its span budget needs a stable order for both sides to see the same rows.
    query = parse_select(
        """
        WITH spans AS (
            SELECT trace_id, span_id, parent_span_id, service_name, status_code, duration_nano
            FROM posthog.trace_spans
            WHERE {where} AND {env_expr} = {environment} AND trace_id IN {trace_ids}
            ORDER BY trace_id, span_id
            LIMIT {span_limit}
        )
        SELECT
            p.service_name AS caller,
            s.service_name AS callee,
            count() AS calls,
            countIf(s.status_code = 2) AS error_count,
            quantile(0.95)(s.duration_nano) / 1e6 AS p95_ms
        FROM spans AS s
        INNER JOIN spans AS p ON p.trace_id = s.trace_id AND p.span_id = s.parent_span_id
        WHERE p.service_name != s.service_name
        GROUP BY caller, callee
        ORDER BY calls DESC, caller, callee
        LIMIT {limit}
        """,
        placeholders={
            "where": _window_where(date_from, date_to),
            "env_expr": environment_expr(),
            "environment": ast.Constant(value=environment),
            "trace_ids": ast.Tuple(exprs=[ast.Constant(value=trace_id) for trace_id in trace_ids]),
            "span_limit": ast.Constant(value=MAP_SPAN_LIMIT),
            "limit": ast.Constant(value=MAP_EDGES_LIMIT),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _sparkline_query(date_from: datetime, date_to: datetime, environment: str) -> ast.SelectQuery:
    # One bucket per point across the window; the client draws the counts in order.
    query = parse_select(
        """
        SELECT
            service_name,
            toInt(floor(dateDiff('second', {date_from}, timestamp) / {bucket_seconds})) AS bucket,
            countIf(kind IN (2, 5)) AS entry_spans,
            countIf(is_root_span) AS root_spans
        FROM posthog.trace_spans
        WHERE {where} AND {env_expr} = {environment}
        GROUP BY service_name, bucket
        ORDER BY service_name, bucket
        LIMIT 100000
        """,
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "bucket_seconds": ast.Constant(
                value=max(1, int((date_to - date_from).total_seconds() // SPARKLINE_POINTS))
            ),
            "where": _window_where(date_from, date_to),
            "env_expr": environment_expr(),
            "environment": ast.Constant(value=environment),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _environments_query(date_from: datetime, date_to: datetime) -> ast.SelectQuery:
    query = parse_select(
        "SELECT {env_expr} AS environment FROM posthog.trace_spans WHERE {where} GROUP BY environment ORDER BY environment LIMIT 50",
        placeholders={"env_expr": environment_expr(), "where": _window_where(date_from, date_to)},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _run(team: Team, query: ast.SelectQuery) -> list:
    return execute_hogql_query(
        query_type="ApmServicesHealthQuery",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=HogQLGlobalSettings(max_execution_time=30),
    ).results


def list_services_health(
    *, team: Team, date_from: datetime, date_to: datetime, environment: str
) -> ServicesHealthResult:
    seconds = max(1.0, (date_to - date_from).total_seconds())
    rows = _run(team, _services_query(date_from, date_to, environment))
    sparklines: dict[str, list[int]] = {}
    has_entry: dict[str, bool] = {row[0]: row[1] > 0 for row in rows}  # row[1] is entry_spans
    for service_name, bucket, entry_spans, root_spans in _run(team, _sparkline_query(date_from, date_to, environment)):
        points = sparklines.setdefault(service_name, [0] * SPARKLINE_POINTS)
        if 0 <= bucket < SPARKLINE_POINTS:
            points[bucket] += entry_spans if has_entry.get(service_name) else root_spans
    services = []
    for service_name, _entry_spans, span_count, error_count, p95_ms in rows:
        if not span_count:
            continue
        health = HealthRow(
            request_rate=span_count / seconds,
            error_rate=error_count / span_count,
            p95_ms=float(p95_ms) if p95_ms is not None else None,
            span_count=int(span_count),
            error_count=int(error_count),
        )
        services.append(
            ServiceHealth(
                service_name=service_name,
                environment=environment,
                health=health,
                sparkline=tuple(sparklines.get(service_name, [0] * SPARKLINE_POINTS)),
            )
        )
    environments = [row[0] for row in _run(team, _environments_query(date_from, date_to))]
    return ServicesHealthResult(services=rank_services(services), environments=environments)


def list_endpoints_health(
    *, team: Team, date_from: datetime, date_to: datetime, environment: str, service: str | None = None
) -> list[EndpointHealth]:
    seconds = max(1.0, (date_to - date_from).total_seconds())
    endpoints = [
        EndpointHealth(
            service_name=service_name,
            endpoint=name,
            environment=environment,
            health=HealthRow(
                request_rate=span_count / seconds,
                error_rate=error_count / span_count,
                p95_ms=float(p95_ms) if p95_ms is not None else None,
                span_count=int(span_count),
                error_count=int(error_count),
            ),
        )
        for service_name, name, span_count, error_count, p95_ms in _run(
            team, _endpoints_query(date_from, date_to, environment, service)
        )
    ]
    return rank_endpoints(endpoints)


def get_service_map(*, team: Team, date_from: datetime, date_to: datetime, environment: str) -> ServiceMapResult:
    # The sample runs once, so the edges and the reported trace count describe the same traces.
    trace_ids = [row[0] for row in _run(team, _sampled_traces_query(date_from, date_to, environment))]
    if not trace_ids:
        return ServiceMapResult(edges=[], trace_count=0)
    edges = [
        ServiceEdge(
            caller=caller,
            callee=callee,
            calls=int(calls),
            error_count=int(error_count),
            p95_ms=float(p95_ms) if p95_ms is not None else None,
        )
        for caller, callee, calls, error_count, p95_ms in _run(
            team, _service_edges_query(date_from, date_to, environment, trace_ids)
        )
    ]
    return ServiceMapResult(edges=edges, trace_count=len(trace_ids))
