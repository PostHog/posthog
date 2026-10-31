from collections.abc import Mapping
from typing import Self

from posthog.dataclasses import frozen

from .trace import Trace


@frozen
class NodeMatch:
    node_id: str
    count: int


@frozen
class TraceSearchResult:
    total: int
    matches: tuple[NodeMatch, ...]

    @classmethod
    def of(cls, trace: Trace, counts: Mapping[str, int], query: str) -> Self:
        """`counts` holds occurrences by event uuid. The root carries the counts of the trace's `$ai_trace` events, or
        the occurrences in its title when it has none, because the root then shows a step's name."""
        root = NodeMatch(node_id=trace.id, count=_root_count(trace, counts, query))
        rows = (NodeMatch(node_id=row.event.id, count=counts.get(row.event.id, 0)) for row in trace.timeline.rows)
        matches = tuple(match for match in (root, *rows) if match.count > 0)
        return cls(total=sum(match.count for match in matches), matches=matches)


def _root_count(trace: Trace, counts: Mapping[str, int], query: str) -> int:
    trace_events = [event for event in trace.events if event.is_trace_event]
    if trace_events:
        return sum(counts.get(event.id, 0) for event in trace_events)
    return trace.title.lower().count(query.lower())
