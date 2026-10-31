"""Reads how much each service sends, per signal, in a window.

Logs bytes come from `_bytes_uncompressed`, the per-record size the logs consumer stores. It is the
same size the billing counter sums, so a service's logs bytes are its share of the billed logs bytes.
Spans and metric points are row counts, which match the billed record counters for traces and
metrics. The traces and metrics consumers do not store a per-record size, so these signals report
counts and not bytes.

Each signal is read with its own query. A signal that fails, for example because its scan times out
on a long window, is reported as unavailable and the other signals still return.
"""

from datetime import datetime

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

logger = structlog.get_logger(__name__)

SERVICES_LIMIT = 500

# This bound lets ClickHouse prune parts by primary key. Buckets start at UTC midnight, so the day is cut
# in UTC: the project timezone would move the bound past buckets inside the window.
_WINDOW_WHERE = (
    "timestamp >= {date_from} AND timestamp < {date_to} "
    "AND time_bucket >= toStartOfDay({date_from}, 'UTC') AND time_bucket <= {date_to}"
)

# The window sums give exact totals even when a team has more services than SERVICES_LIMIT.
LOGS_USAGE_QUERY = f"""
    SELECT
        service_name,
        count() AS records,
        sum(_bytes_uncompressed) AS bytes,
        sum(count()) OVER () AS total_records,
        sum(sum(_bytes_uncompressed)) OVER () AS total_bytes
    FROM logs
    WHERE {_WINDOW_WHERE}
    GROUP BY service_name
    ORDER BY bytes DESC, service_name
    LIMIT {{limit}}
"""

SPANS_USAGE_QUERY = f"""
    SELECT service_name, count() AS spans, sum(count()) OVER () AS total_spans
    FROM posthog.trace_spans
    WHERE {_WINDOW_WHERE}
    GROUP BY service_name
    ORDER BY spans DESC, service_name
    LIMIT {{limit}}
"""

# Series come from the points and not from metric_series: a point without labels writes no metric_series
# row. Each series has one service, so the total counts it once.
METRICS_USAGE_QUERY = f"""
    SELECT
        service_name,
        count() AS points,
        uniq(series_fingerprint) AS series,
        sum(count()) OVER () AS total_points,
        sum(uniq(series_fingerprint)) OVER () AS total_series
    FROM posthog.metrics
    WHERE {_WINDOW_WHERE}
    GROUP BY service_name
    ORDER BY points DESC, service_name
    LIMIT {{limit}}
"""


class UsageSignal(LabeledStrEnum):
    LOGS = "logs"
    TRACES = "traces"
    METRICS = "metrics"


@frozen
class ServiceUsage:
    service_name: str
    log_records: int = 0
    log_bytes: int = 0
    spans: int = 0
    metric_points: int = 0
    metric_series: int = 0


@frozen
class UsageTotals:
    log_records: int = 0
    log_bytes: int = 0
    spans: int = 0
    metric_points: int = 0
    metric_series: int = 0


@frozen
class ServiceUsageResult:
    services: list[ServiceUsage]
    totals: UsageTotals
    unavailable_signals: list[UsageSignal]


@frozen
class _SignalRows:
    # One tuple per service: the service name, then the signal's values in field order.
    rows: list[tuple]
    totals: tuple[int, ...]


def _run(team: Team, sql: str, date_from: datetime, date_to: datetime) -> _SignalRows:
    query = parse_select(
        sql,
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            "limit": ast.Constant(value=SERVICES_LIMIT),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    results = execute_hogql_query(
        query_type="ApmServiceUsageQuery",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=HogQLGlobalSettings(max_execution_time=30),
    ).results
    if not results:
        return _SignalRows(rows=[], totals=())
    width = (len(results[0]) - 1) // 2
    return _SignalRows(
        rows=[(row[0], *(int(value or 0) for value in row[1 : 1 + width])) for row in results],
        totals=tuple(int(value or 0) for value in results[0][1 + width :]),
    )


def list_service_usage(*, team: Team, date_from: datetime, date_to: datetime) -> ServiceUsageResult:
    usage: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    unavailable: list[UsageSignal] = []

    plan: list[tuple[UsageSignal, str, tuple[str, ...]]] = [
        (UsageSignal.LOGS, LOGS_USAGE_QUERY, ("log_records", "log_bytes")),
        (UsageSignal.TRACES, SPANS_USAGE_QUERY, ("spans",)),
        (UsageSignal.METRICS, METRICS_USAGE_QUERY, ("metric_points", "metric_series")),
    ]
    for signal, sql, fields in plan:
        try:
            result = _run(team, sql, date_from, date_to)
        except Exception as error:
            logger.warning("apm_usage_signal_failed", team_id=team.pk, signal=signal.value, exc_info=True)
            capture_exception(error, {"team_id": team.pk, "signal": signal.value})
            unavailable.append(signal)
            continue
        for service_name, *values in result.rows:
            usage.setdefault(service_name, {}).update(zip(fields, values))
        totals.update(zip(fields, result.totals))

    services = [ServiceUsage(service_name=name, **values) for name, values in usage.items()]
    services.sort(key=lambda row: (-row.log_bytes, -row.spans, -row.metric_points, row.service_name))
    return ServiceUsageResult(services=services, totals=UsageTotals(**totals), unavailable_signals=unavailable)
