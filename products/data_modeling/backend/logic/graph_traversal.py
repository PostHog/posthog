"""Pure graph-traversal primitives shared across the data-modeling DAG code.

No Django, no models — just adjacency-map reachability, so the freshness logic and the in-memory
`Graph` share one walk instead of each carrying its own copy. Adjacency values may be any iterable
(sets or lists), since callers build their maps differently.
"""

from collections.abc import Iterable, Mapping


def reachable(start: str, adjacency: Mapping[str, Iterable[str]], max_depth: int | None = None) -> set[str]:
    """All nodes reachable from `start` (exclusive) by following `adjacency`.

    max_depth stops the walk after that many hops, so 1 gives immediate neighbours only.
    Walking level by level is what makes the bound meaningful; an unbounded walk can pop
    in any order.
    """
    seen: set[str] = set()
    frontier = list(adjacency.get(start, ()))
    depth = 1
    while frontier and (max_depth is None or depth <= max_depth):
        next_frontier: list[str] = []
        for node in frontier:
            if node in seen:
                continue
            seen.add(node)
            next_frontier.extend(adjacency.get(node, ()))
        frontier = next_frontier
        depth += 1
    return seen
