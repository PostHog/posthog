"""Reads one service's versions in a window, each compared with the version that came before it.

A version is the `service.version` resource attribute. Requests are entry spans (server and
consumer), with root spans as the fallback for a service that has neither, as on the services tab.
First seen and last seen are the first and last span in the window, so a version that started
before the window shows the window's start.
"""

from dataclasses import dataclass
from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.apm.backend.logic.health.sources import environment_expr, environment_where, window_where

DEPLOYMENTS_LIMIT = 200
MAX_BYTES_TO_READ = 10_000_000_000
MAX_EXECUTION_SECONDS = 30


@dataclass(frozen=True)
class DeploymentVersion:
    version: str
    first_seen: datetime
    last_seen: datetime
    requests: int
    error_count: int
    error_rate: float | None
    p95_ms: float | None
    previous_version: str | None
    error_rate_change: float | None
    p95_change_pct: float | None
    active: bool


def _deployments_query(
    date_from: datetime, date_to: datetime, environment: str | None, service: str
) -> ast.SelectQuery:
    # Entry or root spans are chosen per environment, as on the services tab, so a version that
    # only has root spans in one environment keeps those requests when every environment is read.
    query = parse_select(
        """
        SELECT
            version,
            min(env_first_seen) AS first_seen,
            max(env_last_seen) AS last_seen,
            sum(entry_spans) AS entry_span_count,
            sum(if(entry_spans > 0, entry_errors, root_errors)) AS errors,
            sum(if(entry_spans > 0, entry_spans, root_spans)) AS requests,
            arrayElement(quantilesMerge(0.95)(if(entry_spans > 0, entry_p95, root_p95)), 1) / 1e6 AS p95_ms
        FROM (
            SELECT
                ifNull(resource_attributes['service.version'], '') AS version,
                {env_expr} AS environment,
                min(timestamp) AS env_first_seen,
                max(timestamp) AS env_last_seen,
                countIf(kind IN (2, 5)) AS entry_spans,
                countIf(kind IN (2, 5) AND status_code = 2) AS entry_errors,
                quantilesStateIf(0.95)(duration_nano, kind IN (2, 5)) AS entry_p95,
                countIf(is_root_span) AS root_spans,
                countIf(is_root_span AND status_code = 2) AS root_errors,
                quantilesStateIf(0.95)(duration_nano, is_root_span) AS root_p95
            FROM posthog.trace_spans
            WHERE {where} AND {env_where} AND service_name = {service}
            GROUP BY version, environment
        )
        GROUP BY version
        HAVING version != '' AND requests > 0
        ORDER BY first_seen DESC, version DESC
        LIMIT {limit}
        """,
        placeholders={
            "env_expr": environment_expr(),
            "where": window_where(date_from, date_to),
            "env_where": environment_where(environment),
            "service": ast.Constant(value=service),
            "limit": ast.Constant(value=DEPLOYMENTS_LIMIT),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def compare_versions(rows: list[tuple]) -> list[DeploymentVersion]:
    """Rows oldest first. Each version is compared with the one before it, and the newest is active."""
    versions: list[DeploymentVersion] = []
    for index, (version, first_seen, last_seen, _entry, errors, requests, p95_ms) in enumerate(rows):
        error_rate = errors / requests if requests else None
        p95 = float(p95_ms) if p95_ms is not None else None
        previous = versions[-1] if versions else None
        versions.append(
            DeploymentVersion(
                version=version,
                first_seen=first_seen,
                last_seen=last_seen,
                requests=int(requests),
                error_count=int(errors),
                error_rate=error_rate,
                p95_ms=p95,
                previous_version=previous.version if previous else None,
                error_rate_change=(
                    error_rate - previous.error_rate
                    if previous and error_rate is not None and previous.error_rate is not None
                    else None
                ),
                p95_change_pct=(
                    (p95 - previous.p95_ms) / previous.p95_ms * 100
                    if previous and p95 is not None and previous.p95_ms
                    else None
                ),
                active=index == len(rows) - 1,
            )
        )
    return versions


def list_deployments(
    *, team: Team, date_from: datetime, date_to: datetime, environment: str | None, service: str
) -> list[DeploymentVersion]:
    rows = execute_hogql_query(
        query_type="ApmDeploymentsQuery",
        query=_deployments_query(date_from, date_to, environment, service),
        team=team,
        workload=Workload.LOGS,
        limit_context=LimitContext.QUERY,
        settings=HogQLGlobalSettings(
            max_execution_time=MAX_EXECUTION_SECONDS,
            max_bytes_to_read=MAX_BYTES_TO_READ,
            read_overflow_mode="throw",
        ),
    ).results
    # The query keeps the newest versions under the limit; the comparison walks them oldest first.
    return compare_versions(list(reversed(rows)))
