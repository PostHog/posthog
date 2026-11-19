"""Reads the health row for every service in a window from the spans table.

A service's request rate comes from its entry spans: server spans and consumer spans. A service
that emits neither in an environment, such as a scheduled job, falls back to its root spans there
so it still gets a row.
The environment is the first non-empty resource attribute in the resolution order below, with the
cluster name as the last fallback. A span that sets none of them has the empty environment, which
the API returns as null, so it stays apart from an environment literally named `default`. Every
query filters and groups by the one expression, so a span lands in exactly one environment.
"""

from dataclasses import dataclass
from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.utils.caller_context import map_in_caller_context
from posthog.models import Team

from products.apm.backend.logic.health.contract import (
    APDEX_THRESHOLD_MS,
    EndpointHealth,
    HealthRow,
    ServiceEdge,
    ServiceHealth,
    rank_endpoints,
    rank_services,
)

# Buckets are a share of the window, not a fixed width, so every window has exactly SPARKLINE_POINTS.
SPARKLINE_POINTS = 24
SERVICES_LIMIT = 500
ENDPOINTS_LIMIT = 500
# The map joins spans to their parents, so it reads a bounded sample of traces, not the whole window.
MAP_TRACE_LIMIT = 2000
MAP_EDGES_LIMIT = 1000
# Caps the rows the self-join holds in memory, however many spans the sampled traces carry.
MAP_SPAN_LIMIT = 200_000
NO_ENVIRONMENT = ""

# Many HTTP server instrumentations name a span only by its method and keep the path template in an
# attribute, so a bare-method span gets the template appended: "POST" becomes "POST /users/:id".
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
# Checked in order: http.route is the stable server attribute, url.template the newer generic one.
# A job with no server spans counts its root spans, and those are often an outgoing call named only by
# its method, an HTTP request or a Redis command. Its target names it instead: "GET redis",
# "POST profiles.internal". Hosts and database systems stay few, unlike raw URL paths.
ROUTE_ATTRIBUTES = ("http.route", "url.template", "db.system", "server.address", "net.peer.name")

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
    environments: list[str | None]


@dataclass(frozen=True)
class ServiceMapResult:
    edges: list[ServiceEdge]
    trace_count: int


def environment_expr() -> ast.Expr:
    parts = ", ".join(f"nullIf(resource_attributes['{key}'], '')" for key in ENVIRONMENT_ATTRIBUTES)
    return parse_expr(f"coalesce({parts}, {{unset}})", placeholders={"unset": ast.Constant(value=NO_ENVIRONMENT)})


def environment_where(environment: str | None) -> ast.Expr:
    # None means every environment, so no predicate at all, not a match on some default value.
    if environment is None:
        return ast.Constant(value=True)
    return parse_expr(
        "{env_expr} = {environment}",
        placeholders={"env_expr": environment_expr(), "environment": ast.Constant(value=environment)},
    )


def _apdex_score() -> ast.Expr:
    """1 for a satisfied request, 0.5 for a tolerating one, 0 for a frustrated or failed one."""
    threshold_nano = APDEX_THRESHOLD_MS * 1_000_000
    return parse_expr(
        "multiIf(status_code = 2, 0, duration_nano <= {t}, 1, duration_nano <= {t4}, 0.5, 0)",
        placeholders={"t": ast.Constant(value=threshold_nano), "t4": ast.Constant(value=4 * threshold_nano)},
    )


def _apdex(points: float | None, span_count: int) -> float | None:
    return float(points) / span_count if points is not None and span_count else None


def _route_attribute_read(key: str) -> ast.Expr:
    # The __str suffix routes the read to the typed string map, where a missing key reads as ''.
    return ast.Field(chain=["attributes", f"{key}__str"])


def _route_attribute_is_set(key: str) -> ast.Expr:
    # Compiled the way a span attribute is_set filter is, so both read presence the same way.
    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotEq, left=_route_attribute_read(key), right=ast.Constant(value=None)
    )


def route_attribute_expr() -> ast.Expr:
    """The first route attribute a bare-method span sets, or empty when it isn't one or sets none.

    Precedence goes by presence, the check a span attribute is_set filter makes, so the tracing
    drilldown's is_not_set guards select the same spans. A present but empty route leaves the bare name.
    """
    branches = ", ".join(f"{{set_{i}}}, '{key}'" for i, key in enumerate(ROUTE_ATTRIBUTES))
    return parse_expr(
        f"if(name IN {{methods}}, multiIf({branches}, ''), '')",
        placeholders={
            "methods": ast.Tuple(exprs=[ast.Constant(value=method) for method in HTTP_METHODS]),
            **{f"set_{i}": _route_attribute_is_set(key) for i, key in enumerate(ROUTE_ATTRIBUTES)},
        },
    )


def route_expr() -> ast.Expr:
    """The route a bare-method span carries, read from the attribute route_attribute_expr names."""
    branches = ", ".join(f"{{attribute}} = '{key}', {{read_{i}}}" for i, key in enumerate(ROUTE_ATTRIBUTES))
    return parse_expr(
        f"multiIf({branches}, '')",
        placeholders={
            "attribute": route_attribute_expr(),
            **{f"read_{i}": _route_attribute_read(key) for i, key in enumerate(ROUTE_ATTRIBUTES)},
        },
    )


def endpoint_expr() -> ast.Expr:
    """The endpoint label: "<METHOD> <route>" for a bare-method span with a route, else the span name."""
    return parse_expr(
        "if(notEmpty({route}), concat(name, ' ', {route}), name)",
        placeholders={"route": route_expr()},
    )


def endpoint_span_names(endpoint: str) -> list[str]:
    """The raw span names an endpoint label can come from: itself, plus its method when it has a route."""
    method, _, route = endpoint.partition(" ")
    return [endpoint, method] if route and method in HTTP_METHODS else [endpoint]


def window_where(date_from: datetime, date_to: datetime) -> ast.Expr:
    return parse_expr(
        f"timestamp >= {{date_from}} AND timestamp < {{date_to}} AND {_TIME_BUCKET_DATE_RANGE_WHERE}",
        placeholders={"date_from": ast.Constant(value=date_from), "date_to": ast.Constant(value=date_to)},
    )


def _bucket_counts(date_from: datetime, date_to: datetime) -> ast.Expr:
    """A SPARKLINE_POINTS-long array with a 1 at the span's bucket, for sumForEach to add up per group."""
    return parse_expr(
        "arrayMap(i -> if(i = least(toInt(floor(dateDiff('second', {date_from}, timestamp) * {points} / {window_seconds})), {last_bucket}), 1, 0), range({points}))",
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "points": ast.Constant(value=SPARKLINE_POINTS),
            "window_seconds": ast.Constant(value=max(1.0, (date_to - date_from).total_seconds())),
            "last_bucket": ast.Constant(value=SPARKLINE_POINTS - 1),
        },
    )


def _services_query(date_from: datetime, date_to: datetime, environment: str | None) -> ast.SelectQuery:
    # Server and consumer spans are the request count. Root spans are the fallback for a service with
    # neither in an environment, so a job's client spans count once each rather than once per
    # downstream call. The inner query picks per service and environment in the same scan, and the
    # outer one merges the environments, so the all-environments row is the sum of the per-environment rows.
    # The sparkline applies the same pick, so its points add up to the span count.
    #
    # The sparkline comes from the same scan as the health numbers: reading the window's spans is
    # most of the cost, so a separate sparkline query would nearly double it.
    #
    # A team with more services than SERVICES_LIMIT needs the worst ones to survive the cutoff, so
    # the ranking (error rate, then error count, then name — the same order rank_services applies)
    # runs in SQL before LIMIT, not after.
    query = parse_select(
        """
        SELECT
            service_name,
            sum(if(entry_spans > 0, entry_spans, root_spans)) AS span_count,
            sum(if(entry_spans > 0, entry_errors, root_errors)) AS error_count,
            arrayElement(quantilesMerge(0.95)(if(entry_spans > 0, entry_p95, root_p95)), 1) / 1e6 AS p95_ms,
            sum(if(entry_spans > 0, entry_apdex_points, root_apdex_points)) AS apdex_points,
            sumForEach(if(entry_spans > 0, entry_sparkline, root_sparkline)) AS sparkline
        FROM (
            SELECT
                service_name,
                {env_expr} AS environment,
                countIf(kind IN (2, 5)) AS entry_spans,
                countIf(kind IN (2, 5) AND status_code = 2) AS entry_errors,
                quantilesStateIf(0.95)(duration_nano, kind IN (2, 5)) AS entry_p95,
                sumIf({apdex_score}, kind IN (2, 5)) AS entry_apdex_points,
                sumForEachIf({bucket_counts}, kind IN (2, 5)) AS entry_sparkline,
                countIf(is_root_span) AS root_spans,
                countIf(is_root_span AND status_code = 2) AS root_errors,
                quantilesStateIf(0.95)(duration_nano, is_root_span) AS root_p95,
                sumIf({apdex_score}, is_root_span) AS root_apdex_points,
                sumForEachIf({bucket_counts}, is_root_span) AS root_sparkline
            FROM posthog.trace_spans
            WHERE {where} AND {env_where}
            GROUP BY service_name, environment
        )
        GROUP BY service_name
        HAVING span_count > 0
        ORDER BY error_count / span_count DESC, error_count DESC, service_name
        LIMIT {limit}
        """,
        placeholders={
            "env_expr": environment_expr(),
            "where": window_where(date_from, date_to),
            "env_where": environment_where(environment),
            "limit": ast.Constant(value=SERVICES_LIMIT),
            "apdex_score": _apdex_score(),
            "bucket_counts": _bucket_counts(date_from, date_to),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _endpoints_query(
    date_from: datetime, date_to: datetime, environment: str | None, service: str | None
) -> ast.SelectQuery:
    # An endpoint is an entry span: what a server or consumer span handles, or what a root span
    # starts (a job with no server spans). This is the entry definition the Tracing service health
    # view uses, so a worker's job shows up here the same way it gets a row on the services tab.
    # The span name and route come along so a row can link to the spans it counts.
    query = parse_select(
        """
        SELECT
            service_name,
            endpoint,
            any(name) AS span_name,
            any(route_attribute) AS route_attribute,
            any(route) AS route,
            count() AS span_count,
            countIf(status_code = 2) AS error_count,
            quantile(0.95)(duration_nano) / 1e6 AS p95_ms,
            sum(apdex_score) AS apdex_points
        FROM (
            SELECT
                service_name,
                name,
                status_code,
                duration_nano,
                {apdex_score} AS apdex_score,
                {endpoint} AS endpoint,
                {route_attribute} AS route_attribute,
                {route} AS route
            FROM posthog.trace_spans
            WHERE {where} AND {env_where} AND {service_where} AND (is_root_span OR kind IN (2, 5))
        )
        GROUP BY service_name, endpoint
        ORDER BY error_count / span_count DESC, error_count DESC, service_name, endpoint
        LIMIT {limit}
        """,
        placeholders={
            "endpoint": endpoint_expr(),
            "route_attribute": route_attribute_expr(),
            "route": route_expr(),
            "where": window_where(date_from, date_to),
            "env_where": environment_where(environment),
            "service_where": (
                parse_expr("service_name = {service}", placeholders={"service": ast.Constant(value=service)})
                if service
                else ast.Constant(value=True)
            ),
            "limit": ast.Constant(value=ENDPOINTS_LIMIT),
            "apdex_score": _apdex_score(),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def sampled_traces_query(
    date_from: datetime, date_to: datetime, environment: str | None, trace_where: ast.Expr | None = None
) -> ast.SelectQuery:
    # DISTINCT with LIMIT stops reading once it has enough trace IDs, where GROUP BY would first
    # aggregate every trace in the window.
    query = parse_select(
        """
        SELECT DISTINCT trace_id
        FROM posthog.trace_spans
        WHERE {where} AND {env_where} AND {trace_where}
        LIMIT {limit}
        """,
        placeholders={
            "where": window_where(date_from, date_to),
            "env_where": environment_where(environment),
            "trace_where": trace_where or ast.Constant(value=True),
            "limit": ast.Constant(value=MAP_TRACE_LIMIT),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _service_edges_query(
    date_from: datetime, date_to: datetime, environment: str | None, trace_ids: list[str]
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
            WHERE {where} AND {env_where} AND trace_id IN {trace_ids}
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
            "where": window_where(date_from, date_to),
            "env_where": environment_where(environment),
            "trace_ids": ast.Tuple(exprs=[ast.Constant(value=trace_id) for trace_id in trace_ids]),
            "span_limit": ast.Constant(value=MAP_SPAN_LIMIT),
            "limit": ast.Constant(value=MAP_EDGES_LIMIT),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _environments_query(date_from: datetime, date_to: datetime) -> ast.SelectQuery:
    query = parse_select(
        "SELECT {env_expr} AS environment FROM posthog.trace_spans WHERE {where} GROUP BY environment ORDER BY environment LIMIT 50",
        placeholders={"env_expr": environment_expr(), "where": window_where(date_from, date_to)},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _sparkline_points(counts: list[int]) -> tuple[int, ...]:
    # sumForEach returns an empty array for a group none of whose picked spans matched.
    return tuple(int(count) for count in counts[:SPARKLINE_POINTS]) + (0,) * max(0, SPARKLINE_POINTS - len(counts))


def _run(team: Team, query: ast.SelectQuery) -> list:
    return execute_hogql_query(
        query_type="ApmServicesHealthQuery",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=HogQLGlobalSettings(max_execution_time=30),
    ).results


def list_services_health(
    *, team: Team, date_from: datetime, date_to: datetime, environment: str | None
) -> ServicesHealthResult:
    seconds = max(1.0, (date_to - date_from).total_seconds())
    # Independent scans of the same window, so they run side by side rather than one after the other.
    rows, environment_rows = map_in_caller_context(
        lambda query: _run(team, query),
        [_services_query(date_from, date_to, environment), _environments_query(date_from, date_to)],
        thread_name_prefix="apm_services_health",
    )
    services = []
    for service_name, span_count, error_count, p95_ms, apdex_points, sparkline in rows:
        if not span_count:
            continue
        health = HealthRow(
            request_rate=span_count / seconds,
            error_rate=error_count / span_count,
            p95_ms=float(p95_ms) if p95_ms is not None else None,
            span_count=int(span_count),
            error_count=int(error_count),
            apdex=_apdex(apdex_points, span_count),
        )
        services.append(
            ServiceHealth(
                service_name=service_name,
                environment=environment,
                health=health,
                sparkline=_sparkline_points(sparkline),
            )
        )
    environments = [row[0] or None for row in environment_rows]
    return ServicesHealthResult(services=rank_services(services), environments=environments)


def list_endpoints_health(
    *, team: Team, date_from: datetime, date_to: datetime, environment: str | None, service: str | None = None
) -> list[EndpointHealth]:
    seconds = max(1.0, (date_to - date_from).total_seconds())
    endpoints = [
        EndpointHealth(
            service_name=service_name,
            endpoint=endpoint,
            span_name=span_name,
            route_attribute=route_attribute if route else None,
            route=route or None,
            environment=environment,
            health=HealthRow(
                request_rate=span_count / seconds,
                error_rate=error_count / span_count,
                p95_ms=float(p95_ms) if p95_ms is not None else None,
                span_count=int(span_count),
                error_count=int(error_count),
                apdex=_apdex(apdex_points, span_count),
            ),
        )
        for service_name, endpoint, span_name, route_attribute, route, span_count, error_count, p95_ms, apdex_points in _run(
            team, _endpoints_query(date_from, date_to, environment, service)
        )
    ]
    return rank_endpoints(endpoints)


def get_service_map(*, team: Team, date_from: datetime, date_to: datetime, environment: str | None) -> ServiceMapResult:
    # The sample runs once, so the edges and the reported trace count describe the same traces.
    trace_ids = [row[0] for row in _run(team, sampled_traces_query(date_from, date_to, environment))]
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
