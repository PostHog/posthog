import logging
from collections import defaultdict, deque
from typing import Any

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.table import DataWarehouseTable


class LineageViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    scope_object = "INTERNAL"

    def safely_get_queryset(self, queryset=None):
        return super().safely_get_queryset(queryset).filter(team_id=self.team_id)

    @action(detail=False, methods=["GET"])
    def get_upstream(self, request, *args, **kwargs):
        model_id = request.query_params.get("model_id")

        if not model_id:
            return Response({"error": "model_id is required"}, status=400)

        return Response(get_upstream_dag(self.team_id, model_id))


def topological_sort(nodes: list[str], edges: list[dict[str, str]]) -> list[str]:
    """
    Performs a topological sort on the DAG to determine execution order.
    Returns nodes ordered from most upstream to the node itself.
    """
    # Build adjacency list and in-degree count
    graph = defaultdict(list)
    in_degree: dict[str, int] = defaultdict(int)

    for edge in edges:
        source, target = edge["source"], edge["target"]
        graph[source].append(target)
        in_degree[target] += 1
        if source not in in_degree:
            in_degree[source] = 0

    # Initialize queue with nodes that have no incoming edges
    queue = deque([node for node in nodes if in_degree[node] == 0])
    result = []

    # Process nodes
    while queue:
        node = queue.popleft()
        result.append(node)

        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return result


def get_upstream_dag(team_id: int, model_id: str) -> dict[str, list[Any]]:
    dag: dict[str, list[Any]] = {"nodes": [], "edges": []}
    seen_nodes: set[str] = set()
    node_data: dict[str, dict] = {}

    # root node and its external tables
    root_query = DataWarehouseSavedQuery.objects.filter(id=model_id, team_id=team_id).first()
    if not root_query:
        return dag

    node_data[root_query.name] = {
        "id": root_query.name,
        "type": "view",
        "name": root_query.name,
        "sync_frequency": root_query.sync_frequency_interval,
        "last_run_at": root_query.last_run_at,
        "status": root_query.status,
    }
    seen_nodes.add(root_query.name)

    # Recursively fetch all dependencies with a bfs
    # Fetch everything by names, ids and names are the same right now
    to_process = [(root_query.name, root_query.external_tables)]

    while to_process:
        current_id, external_tables = to_process.pop(0)

        # Batch lookup all external tables at this level
        unseen_external_tables = [et for et in external_tables if et not in seen_nodes]
        if unseen_external_tables:
            saved_queries = {
                sq.name: sq
                for sq in DataWarehouseSavedQuery.objects.filter(name__in=unseen_external_tables, team_id=team_id)
            }
            tables = {
                t.name: t for t in DataWarehouseTable.objects.filter(name__in=unseen_external_tables, team_id=team_id)
            }

        for external_table in external_tables:
            edge = {"source": external_table, "target": current_id}
            if edge not in dag["edges"]:
                dag["edges"].append(edge)

            if external_table not in seen_nodes:
                seen_nodes.add(external_table)

                # Process the current external table
                saved_query = saved_queries.get(external_table)
                if saved_query:
                    node_data[external_table] = {
                        "id": external_table,
                        "type": "view",
                        "name": saved_query.name,
                        "sync_frequency": saved_query.sync_frequency_interval,
                        "last_run_at": saved_query.last_run_at,
                        "status": saved_query.status,
                    }
                    to_process.append((external_table, saved_query.external_tables))
                else:
                    table = tables.get(external_table)
                    if not table:
                        logging.warning(f"Upstream table not found for external_table: {external_table}")
                    node_data[external_table] = {
                        "id": external_table,
                        "type": "table",
                        "name": table.name if table else external_table,
                    }

    # Order nodes by dependency order
    ordered_nodes = topological_sort(list(node_data.keys()), dag["edges"])
    dag["nodes"] = [node_data[node_id] for node_id in ordered_nodes]

    return dag
