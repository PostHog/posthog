from collections.abc import Iterator, Mapping
from typing import Self

from posthog.dataclasses import frozen

from .trace import Trace
from .tree import TreeNode


@frozen
class NodeMatch:
    node_id: str
    count: int


@frozen
class TraceSearchResult:
    total: int
    matches: tuple[NodeMatch, ...]

    @classmethod
    def of(cls, trace: Trace, counts: Mapping[str, int]) -> Self:
        """`counts` holds occurrences by event uuid. The root carries the counts of the trace's `$ai_trace` events."""
        root = NodeMatch(
            node_id=trace.id,
            count=sum(counts.get(event.id, 0) for event in trace.events if event.is_trace_event),
        )
        tree = (NodeMatch(node_id=node.event.id, count=counts.get(node.event.id, 0)) for node in _pre_order(trace.tree))
        matches = tuple(match for match in (root, *tree) if match.count > 0)
        return cls(total=sum(match.count for match in matches), matches=matches)


def _pre_order(nodes: tuple[TreeNode, ...]) -> Iterator[TreeNode]:
    for node in nodes:
        yield node
        yield from _pre_order(node.children)
