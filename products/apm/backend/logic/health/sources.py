"""Reads the health row for every service in a window from the spans table.

A service's request rate comes from its server spans. A service that emits no server spans, which
is every consumer and worker in practice, falls back to its root spans so it still gets a row.
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

from products.apm.backend.logic.health.contract import HealthRow, ServiceHealth, rank_services

SPARKLINE_POINTS = 24
SERVICES_LIMIT = 500
DEFAULT_ENVIRONMENT = "default"

ENVIRONMENT_ATTRIBUTES = (
    "deployment.environment.name",
    "deployment.environment",
    "env",
    "k8s.cluster.name",
)


@dataclass(frozen=True)
class ServicesHealthResult:
    services: list[ServiceHealth]
    environments: list[str]


def environment_expr() -> ast.Expr:
    parts = ", ".join(f"nullIf(resource_attributes['{key}'], '')" for key in ENVIRONMENT_ATTRIBUTES)
    return parse_expr(
        f"coalesce({parts}, {{default}})", placeholders={"default": ast.Constant(value=DEFAULT_ENVIRONMENT)}
    )


def _window_where(date_from: datetime, date_to: datetime) -> ast.Expr:
    return parse_expr(
        "timestamp >= {date_from} AND timestamp < {date_to}",
        placeholders={"date_from": ast.Constant(value=date_from), "date_to": ast.Constant(value=date_to)},
    )


def _services_query(date_from: datetime, date_to: datetime, environment: str) -> ast.SelectQuery:
    # Server spans are the request count. Root spans are the fallback for services with none, so a
    # consumer's client spans count once each rather than once per downstream call.
    query = parse_select(
        """
        SELECT
            service_name,
            countIf(kind = 2) AS server_spans,
            if(countIf(kind = 2) > 0, countIf(kind = 2), countIf(is_root_span)) AS span_count,
            if(countIf(kind = 2) > 0, countIf(kind = 2 AND status_code = 2), countIf(is_root_span AND status_code = 2)) AS error_count,
            if(countIf(kind = 2) > 0,
               quantileIf(0.95)(duration_nano, kind = 2),
               quantileIf(0.95)(duration_nano, is_root_span)) / 1e6 AS p95_ms
        FROM posthog.trace_spans
        WHERE {where} AND {env_expr} = {environment}
        GROUP BY service_name
        ORDER BY service_name
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


def _sparkline_query(date_from: datetime, date_to: datetime, environment: str) -> ast.SelectQuery:
    # One bucket per point across the window; the client draws the counts in order.
    query = parse_select(
        """
        SELECT
            service_name,
            toInt(floor(dateDiff('second', {date_from}, timestamp) / {bucket_seconds})) AS bucket,
            countIf(kind = 2) AS server_spans,
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
    has_server: dict[str, bool] = {row[0]: row[1] > 0 for row in rows}  # row[1] is server_spans
    for service_name, bucket, server_spans, root_spans in _run(team, _sparkline_query(date_from, date_to, environment)):
        points = sparklines.setdefault(service_name, [0] * SPARKLINE_POINTS)
        if 0 <= bucket < SPARKLINE_POINTS:
            points[bucket] += server_spans if has_server.get(service_name) else root_spans
    services = []
    for service_name, _server_spans, span_count, error_count, p95_ms in rows:
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
