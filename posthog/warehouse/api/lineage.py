from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework.permissions import IsAuthenticated
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from typing import Any
from collections import defaultdict, deque
from django.db.models import Q
import uuid
from posthog.warehouse.models.modeling import DataWarehouseModelPath
from posthog.warehouse.models.table import DataWarehouseTable
import logging


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

    # root node and its external tables
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return result


def get_upstream_dag(team_id: int, model_id: str) -> dict[str, list[Any]]:
    dag: dict[str, list[Any]] = {"nodes": [], "edges": []}
    seen_nodes: set[str] = set()
    node_data: dict[str, dict] = {}

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
    # Fetch all dependencies with a bfs
    # Fetch everything by names, ids and names are the same right now
    to_process = [(root_query.name, root_query.external_tables, [])]

    while to_process:
        current_name, external_tables, saved_query_names = to_process.pop(0)

        current_saved_query = DataWarehouseSavedQuery.objects.filter(name=current_name, team_id=team_id).first()
        if current_saved_query:
            query = Q(team_id=team_id, saved_query_id=current_saved_query.id)
            paths = DataWarehouseModelPath.objects.filter(query)

            for path in paths:
                components = path.path if isinstance(path.path, list) else path.path.split(".")
                for component in components:
                    try:
                        uuid.UUID(component)
                        if (
                            DataWarehouseSavedQuery.objects.filter(id=component, team_id=team_id).exists()
                            and component != current_saved_query.id
                        ):
                            saved_query = DataWarehouseSavedQuery.objects.get(id=component, team_id=team_id)
                            saved_query_names.append(saved_query.name)
                    except ValueError:
                        continue

        #  Deduplicate dependencies, which would be materialized views since they are both external and in the model paths
        all_dependencies = list(dict.fromkeys(external_tables + saved_query_names))

        unseen_dependencies = [dep for dep in all_dependencies if dep not in seen_nodes]
        if unseen_dependencies:
            saved_query_names = []
            table_names = []
            for dep in unseen_dependencies:
                if DataWarehouseSavedQuery.objects.filter(name=dep, team_id=team_id).exists():
                    saved_query_names.append(dep)
                else:
                    table_names.append(dep)

            saved_queries = {
                q.name: q for q in DataWarehouseSavedQuery.objects.filter(name__in=saved_query_names, team_id=team_id)
            }
            tables = {t.name: t for t in DataWarehouseTable.objects.filter(name__in=table_names, team_id=team_id)}

        for dependency in all_dependencies:
            if dependency != current_name:
                edge = {"source": dependency, "target": current_name}
                if edge not in dag["edges"]:
                    dag["edges"].append(edge)

            if dependency not in seen_nodes:
                seen_nodes.add(dependency)

                saved_query = saved_queries.get(dependency)
                if saved_query:
                    node_data[dependency] = {
                        "id": dependency,
                        "type": "view",
                        "name": saved_query.name,
                        "sync_frequency": saved_query.sync_frequency_interval,
                        "last_run_at": saved_query.last_run_at,
                        "status": saved_query.status,
                    }
                    to_process.append((saved_query.name, saved_query.external_tables, []))
                else:
                    table = tables.get(dependency)
                    if not table:
                        logging.warning(f"Upstream table not found for dependency: {dependency}")
                    node_data[dependency] = {
                        "id": dependency,
                        "type": "table",
                        "name": table.name if table else dependency,
                    }

    ordered_nodes = topological_sort(list(node_data.keys()), dag["edges"])
    if root_query.name not in ordered_nodes:
        ordered_nodes.append(root_query.name)
    dag["nodes"] = [node_data[node_id] for node_id in ordered_nodes]

    return dag
