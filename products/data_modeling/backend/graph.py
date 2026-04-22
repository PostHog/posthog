"""In-memory DAG graph traversal utilities.

Loads edges once and computes upstream/downstream relationships in Python
instead of running recursive DB queries per node.
"""

from collections import defaultdict, deque
from uuid import UUID

from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import NodeType


def _bfs(start: str, adjacency: dict[str, set[str]]) -> set[str]:
    """BFS from start, returning all reachable nodes (excluding start)."""
    visited: set[str] = set()
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return visited


class Graph:
    """In-memory representation of a DAG's edge structure.

    Loads all edges for the given scope in a single query, then supports
    O(V+E) traversal for upstream/downstream lookups.
    """

    def __init__(
        self,
        team_id: int,
        dag_id: UUID | str | None = None,
        exclude_table_sources: bool = True,
        exclude_table_targets: bool = True,
    ):
        """Load edges and build adjacency maps.

        Args:
            team_id: filter edges to this team
            dag_id: if set, filter to a single DAG; otherwise load all DAGs
            exclude_table_sources: skip edges whose source is a TABLE node (for upstream counts)
            exclude_table_targets: skip edges whose target is a TABLE node (for downstream counts)
        """
        qs = Edge.objects.filter(team_id=team_id)
        if dag_id:
            qs = qs.filter(dag_id=dag_id)

        # Fetch edges with source/target types in a single query
        edge_rows = list(
            qs.select_related("source", "target").values_list("source_id", "target_id", "source__type", "target__type")
        )

        # Build separate adjacency maps for upstream (excluding table sources)
        # and downstream (excluding table targets) to match the old behavior
        self._upstream_adj: dict[str, set[str]] = defaultdict(set)  # target -> sources
        self._downstream_adj: dict[str, set[str]] = defaultdict(set)  # source -> targets

        for source_id, target_id, source_type, target_type in edge_rows:
            s = str(source_id)
            t = str(target_id)
            if not exclude_table_sources or source_type != NodeType.TABLE:
                self._upstream_adj[t].add(s)
            if not exclude_table_targets or target_type != NodeType.TABLE:
                self._downstream_adj[s].add(t)

    def get_upstream(self, node_id: str | UUID) -> set[str]:
        """Get all upstream (ancestor) node IDs, excluding TABLE nodes."""
        return _bfs(str(node_id), self._upstream_adj)

    def get_downstream(self, node_id: str | UUID) -> set[str]:
        """Get all downstream (descendant) node IDs, excluding TABLE nodes."""
        return _bfs(str(node_id), self._downstream_adj)

    def get_upstream_count(self, node_id: str | UUID) -> int:
        return len(self.get_upstream(node_id))

    def get_downstream_count(self, node_id: str | UUID) -> int:
        return len(self.get_downstream(node_id))

    def batch_counts(self, node_ids: list[str]) -> dict[str, tuple[int, int]]:
        """Compute (upstream_count, downstream_count) for a batch of nodes.

        Returns a dict of node_id -> (upstream_count, downstream_count).
        """
        result: dict[str, tuple[int, int]] = {}
        for nid in node_ids:
            key = str(nid)
            result[key] = (self.get_upstream_count(key), self.get_downstream_count(key))
        return result
