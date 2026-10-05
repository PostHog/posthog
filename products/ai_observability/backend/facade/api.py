from datetime import datetime

from posthog.models import Team, User

from ..logic.traces.timeline import TimelineRow
from ..logic.traces.trace import Trace
from ..logic.traces.trace_queries import fallback_window, load_trace
from ..logic.traces.tree import TreeNode
from ..logic.traces.usage import Usage
from . import contracts


class TraceNotFoundError(Exception):
    pass


def is_usable_timestamp_hint(timestamp_hint: datetime) -> bool:
    try:
        fallback_window(timestamp_hint)
    except OverflowError:
        return False
    return True


def get_trace(team: Team, user: User | None, trace_id: str, timestamp_hint: datetime | None) -> contracts.Trace:
    loaded = load_trace(team, user, trace_id, timestamp_hint)
    if not loaded.rows:
        raise TraceNotFoundError(trace_id)
    return _to_trace(Trace(trace_id, loaded.rows, loaded.person))


def _to_stats(usage: Usage) -> contracts.TraceNodeStats:
    return contracts.TraceNodeStats(
        cost_usd=usage.cost_usd,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        latency_ms=usage.latency_ms,
    )


def _to_node(node: TreeNode) -> contracts.TraceNode:
    return contracts.TraceNode(
        id=node.event.id,
        kind=node.event.kind,
        name=node.event.title,
        model=node.event.row.model,
        stats=_to_stats(node.display_usage),
        has_error=node.event.has_error,
        children=[_to_node(child) for child in node.children],
    )


def _to_timeline_row(row: TimelineRow) -> contracts.TraceTimelineRow:
    return contracts.TraceTimelineRow(
        id=row.event.id,
        kind=row.event.kind,
        name=row.event.timeline_label,
        depth=row.depth,
        start_ms=row.start_ms,
        duration_ms=row.duration_ms,
        has_error=row.event.has_error,
    )


def _to_trace(trace: Trace) -> contracts.Trace:
    totals = _to_stats(trace.totals)
    person = (
        contracts.TracePerson(distinct_id=trace.person.distinct_id, label=trace.person_label)
        if trace.person is not None and trace.person_label is not None
        else None
    )
    root = contracts.TraceNode(
        id=trace.id,
        kind="trace",
        name=trace.title,
        model=None,
        stats=totals,
        has_error=trace.has_error,
        children=[_to_node(node) for node in trace.tree],
    )
    return contracts.Trace(
        id=trace.id,
        name=trace.name,
        created_at=trace.created_at,
        session_id=trace.session_id,
        person=person,
        totals=totals,
        has_error=trace.has_error,
        error_count=trace.error_count,
        tree=[root],
        timeline=[_to_timeline_row(row) for row in trace.timeline.rows],
        total_ms=trace.timeline.total_ms,
        thread_node_ids=trace.thread_node_ids,
    )
