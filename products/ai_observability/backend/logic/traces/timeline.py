from collections.abc import Iterator, Sequence

from posthog.dataclasses import frozen

from .event import TraceEvent
from .tree import TreeNode


@frozen
class TimelineRow:
    event: TraceEvent
    depth: int
    start_ms: float
    duration_ms: float | None


@frozen
class Timeline:
    rows: tuple[TimelineRow, ...]
    total_ms: float

    @classmethod
    def from_tree(cls, roots: Sequence[TreeNode]) -> "Timeline":
        walked = list(_pre_order(roots, depth=0))
        if not walked:
            return cls(rows=(), total_ms=0.0)
        origin = min(node.event.started_at for node, _ in walked)
        rows = tuple(
            TimelineRow(
                event=node.event,
                depth=depth,
                start_ms=(node.event.started_at - origin).total_seconds() * 1000,
                duration_ms=node.event.usage.latency_ms,
            )
            for node, depth in walked
        )
        return cls(rows=rows, total_ms=max(row.start_ms + (row.duration_ms or 0) for row in rows))


def _pre_order(nodes: Sequence[TreeNode], depth: int) -> Iterator[tuple[TreeNode, int]]:
    for node in nodes:
        yield node, depth
        yield from _pre_order(node.children, depth + 1)
