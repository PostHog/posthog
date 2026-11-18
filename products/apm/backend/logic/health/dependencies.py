"""Reads who calls whom in a window, including dependencies that send no spans of their own.

A service edge is a server or consumer span whose parent span is in another service. An inferred
edge is a client or producer span with no client, producer or entry child span, whose attributes name what it called: a peer
service, a database, a queue or a host. A call with no child whose target is a service with spans
in the window counts on that service's edge, so a call that never arrived still shows its failure.

Every edge is measured on the caller's side when the caller has a client or producer span, since
that is the latency and the errors the caller saw. Without one, the callee span is used.

A window with up to EXACT_SPAN_LIMIT spans is read whole, so the counts add up to the spans in it.
A busier window is sampled by time: the join reads evenly spaced slices of the window that hold about
EXACT_SPAN_LIMIT spans, child margins included, judged from a count of spans per minute. The counts are
scaled back up by the share of the window's spans that start in the slices, counted exactly, so a burst
in one part of the window doesn't skew them.
Slices of time, not of trace ids, because the timestamp index skips the granules outside a slice,
while a hash of the trace id matches a row in nearly every granule and saves no reads.
Fail-fast settings still cap the bytes read and the run time.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
# The most spans the join reads before it samples. The query scans the window about four times and
# reads the attributes map in two of those scans, so this keeps a sampled run well under the byte cap.
EXACT_SPAN_LIMIT = 4_000_000
SAMPLE_SLICE_SECONDS = 60
MIN_SAMPLE_SLICE_SECONDS = 1.0
MAX_SAMPLE_SLICES = 30
# A child span starts after its parent, give or take clock skew between hosts, so the child side reads
# a little past each slice to find the children of parents that start near its end.
CHILD_MARGIN = timedelta(seconds=10)

_ENTRY_KINDS = "(2, 5)"
# A left join leaves the callee columns null for a span with no matching child span.
# HogQL reads a null comparison as true, so the test goes through a function that maps null to false.
_HAS_CALLEE = "notEmpty(ifNull(c.service_name, ''))"
_CALL_KINDS = "(3, 4)"


def _attr(key: str) -> str:
    # `attributes` is an alias that rebuilds the whole map for every row, so the key is read from the
    # type-suffixed backing map instead. arrayElement returns an empty string for a missing key, where
    # HogQL's subscript returns null and reads a null comparison as true.
    return f"arrayElement(attributes_map_str, '{key}__str')"


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
    sampled: bool
    sample_rate: float


@dataclass(frozen=True)
class _Sample:
    slices: list[tuple[datetime, datetime]]


@dataclass(frozen=True)
class _SpanDensity:
    """Spans per minute in a window, read as spread evenly within each minute."""

    starts: list[float]
    ends: list[float]
    counts: list[int]
    before: list[int]

    @classmethod
    def from_minutes(cls, minute_counts: list[tuple[datetime, int]], date_from: datetime, date_to: datetime):
        starts, ends, counts, before, total = [], [], [], [], 0
        for minute, count in sorted(minute_counts):
            minute = minute if minute.tzinfo else minute.replace(tzinfo=UTC)
            start = (max(minute, date_from) - date_from).total_seconds()
            end = (min(minute + timedelta(minutes=1), date_to) - date_from).total_seconds()
            if end <= start or count <= 0:
                continue
            starts.append(start)
            ends.append(end)
            counts.append(count)
            before.append(total)
            total += count
        return cls(starts=starts, ends=ends, counts=counts, before=before)

    @property
    def total(self) -> int:
        return self.before[-1] + self.counts[-1] if self.counts else 0

    def spans_before(self, seconds: float) -> float:
        i = bisect_right(self.starts, seconds) - 1
        if i < 0:
            return 0
        share = min(seconds - self.starts[i], self.ends[i] - self.starts[i]) / (self.ends[i] - self.starts[i])
        return self.before[i] + self.counts[i] * share


def _plan_sample(density: _SpanDensity, date_from: datetime, date_to: datetime) -> _Sample | None:
    total = density.total
    if total <= EXACT_SPAN_LIMIT:
        return None
    window_seconds = (date_to - date_from).total_seconds()
    count = min(
        MAX_SAMPLE_SLICES,
        max(1, round(window_seconds * EXACT_SPAN_LIMIT / total / SAMPLE_SLICE_SECONDS)),
    )
    stride = window_seconds / count
    margin = CHILD_MARGIN.total_seconds()

    def reads(width: float) -> float:
        # The child scans read each slice widened by the margin, so the margin counts against the limit.
        return sum(
            density.spans_before(min(window_seconds, i * stride + width + margin))
            - density.spans_before(max(0.0, i * stride - margin))
            for i in range(count)
        )

    # The widest slices that read at most the limit. A burst denser than the limit in a single second
    # still gets a one-second slice, and the fail-fast settings cap that read.
    low, high = MIN_SAMPLE_SLICE_SECONDS, stride
    for _ in range(30):
        middle = (low + high) / 2
        if reads(middle) <= EXACT_SPAN_LIMIT:
            low = middle
        else:
            high = middle
    width = timedelta(seconds=low)
    slices = [
        (date_from + timedelta(seconds=i * stride), date_from + timedelta(seconds=i * stride) + width)
        for i in range(count)
    ]
    return _Sample(slices=slices)


def _sample_where(
    date_from: datetime, date_to: datetime, sample: _Sample | None, margin: timedelta = timedelta(0)
) -> ast.Expr:
    if sample is None:
        return window_where(date_from, date_to)
    ranges = [
        parse_expr(
            "timestamp >= {start} AND timestamp < {end}",
            placeholders={
                "start": ast.Constant(value=max(date_from, start - margin)),
                "end": ast.Constant(value=min(date_to, end + margin)),
            },
        )
        for start, end in sample.slices
    ]
    return ast.And(exprs=[window_where(date_from, date_to), ast.Or(exprs=ranges)])


def _span_count_query(
    date_from: datetime,
    date_to: datetime,
    environment: str | None,
    service: str | None,
    sample: _Sample | None = None,
) -> ast.SelectQuery:
    # Without a sample it counts the window's spans per minute to plan one; with one, the spans the
    # join reads as parents, which sets the scale.
    query = parse_select(
        (
            "SELECT count() FROM posthog.trace_spans WHERE {where} AND {env_where} AND {trace_where}"
            if sample
            else "SELECT toStartOfMinute(timestamp) AS minute, count() FROM posthog.trace_spans"
            " WHERE {where} AND {env_where} AND {trace_where} GROUP BY minute"
        ),
        placeholders={
            "where": _sample_where(date_from, date_to, sample),
            "env_where": environment_where(environment),
            "trace_where": _service_traces_where(date_from, date_to, environment, service),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _dependencies_query(
    date_from: datetime,
    date_to: datetime,
    environment: str | None,
    service: str | None,
    sample: _Sample | None = None,
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
            WHERE {{parent_where}} AND {{env_where}} AND {{trace_where}}
        ) AS p
        LEFT JOIN (
            SELECT trace_id, parent_span_id, service_name, status_code, duration_nano
            FROM posthog.trace_spans
            WHERE {{child_where}} AND {{env_where}} AND {{trace_where}}
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
                WHERE {{child_where}} AND {{env_where}} AND {{trace_where}}
                    AND kind IN {_CALL_KINDS} AND NOT is_root_span
            ) AS x
            LEFT JOIN (
                SELECT trace_id, parent_span_id, service_name
                FROM posthog.trace_spans
                WHERE {{child_where}} AND {{env_where}} AND {{trace_where}}
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
            "parent_where": _sample_where(date_from, date_to, sample),
            "child_where": _sample_where(date_from, date_to, sample, CHILD_MARGIN),
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
    # Reading any attribute costs about as much as reading the whole attributes map for every span
    # in the window, which alone can pass the byte cap on an hour. A call span that names the service
    # carries it, or the database or queue system before the first colon, as a whole attribute value,
    # so the bloom filter index on the map values skips the granules that cannot match.
    values = [service] if ":" not in service else [service, service.split(":", 1)[0]]
    return parse_expr(
        f"""trace_id IN (
            SELECT trace_id FROM posthog.trace_spans
            WHERE {{where}} AND {{env_where}} AND service_name = {{service}}
        ) OR trace_id IN (
            SELECT trace_id FROM posthog.trace_spans
            WHERE {{where}} AND {{env_where}} AND kind IN {_CALL_KINDS}
                AND hasAny(mapValues(attributes_map_str), {{values}}) AND {_TARGET} = {{service}}
        )""",
        placeholders={
            "where": window_where(date_from, date_to),
            "env_where": environment_where(environment),
            "service": ast.Constant(value=service),
            "values": ast.Array(exprs=[ast.Constant(value=value) for value in values]),
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


def _run(team: Team, query_type: str, query: ast.SelectQuery) -> list:
    return execute_hogql_query(
        query_type=query_type,
        query=query,
        team=team,
        workload=Workload.LOGS,
        limit_context=LimitContext.QUERY,
        settings=HogQLGlobalSettings(
            max_execution_time=MAX_EXECUTION_SECONDS,
            max_bytes_to_read=MAX_BYTES_TO_READ,
            read_overflow_mode="throw",
        ),
    ).results


def _scale(value: int, rate: float) -> int:
    return value if rate >= 1 else math.floor(value / rate + 0.5)


def get_dependencies(
    *, team: Team, date_from: datetime, date_to: datetime, environment: str | None, service: str | None = None
) -> DependenciesResult:
    minutes = _run(team, "ApmDependenciesSpanCount", _span_count_query(date_from, date_to, environment, service))
    density = _SpanDensity.from_minutes([(minute, int(count)) for minute, count in minutes], date_from, date_to)
    sample = _plan_sample(density, date_from, date_to)
    rate = 1.0
    if sample:
        sampled = _run(
            team, "ApmDependenciesSampleCount", _span_count_query(date_from, date_to, environment, service, sample)
        )
        rate = min(1.0, max(1, int(sampled[0][0])) / density.total)
    rows = _run(team, "ApmDependenciesQuery", _dependencies_query(date_from, date_to, environment, service, sample))
    edges = [
        DependencyEdge(
            caller=caller,
            callee=callee,
            inferred=bool(inferred),
            kind=DependencyKind(kind),
            requests=_scale(int(requests), rate),
            error_count=_scale(int(error_count), rate),
            p95_ms=float(p95_ms) if p95_ms is not None else None,
        )
        for caller, callee, inferred, kind, requests, error_count, p95_ms in rows[:DEPENDENCY_EDGES_LIMIT]
    ]
    return DependenciesResult(
        edges=edges, truncated=len(rows) > DEPENDENCY_EDGES_LIMIT, sampled=sample is not None, sample_rate=rate
    )
