"""Pure graph-traversal primitives shared across the data-modeling DAG code.

No Django, no models — just adjacency-map reachability, so the freshness logic and the in-memory
`Graph` share one walk instead of each carrying its own copy. Adjacency values may be any iterable
(sets or lists), since callers build their maps differently.
"""

from collections.abc import Iterable, Mapping


def reachable(start: str, adjacency: Mapping[str, Iterable[str]]) -> set[str]:
    """All nodes reachable from `start` (exclusive) by following `adjacency`."""
    seen: set[str] = set()
    stack = list(adjacency.get(start, ()))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, ()))
    return seen
