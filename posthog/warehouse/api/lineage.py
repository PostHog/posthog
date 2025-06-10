from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from posthog.warehouse.models.modeling import DataWarehouseModelPath
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework.permissions import IsAuthenticated
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
import uuid
from typing import Optional, Any
from collections import defaultdict, deque


def join_components_greedily(components: list[str]) -> list[str]:
    """
    Greedily joins components until hitting a UUID.
    Returns a list where UUIDs are separate items and non-UUID components are joined.
    """
    new_components: list[str] = []
    current_group: list[str] = []

    for component in components:
        try:
            uuid.UUID(component)
            if current_group:
                new_components.append(".".join(current_group))
                current_group = []
            new_components.append(component)
        except ValueError:
            current_group.append(component)

    if current_group:
        new_components.append(".".join(current_group))

    return new_components


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
    Returns nodes ordered from most upstream to most downstream.
    """
    # Build adjacency list and in-degree count
    graph = defaultdict(list)
    in_degree = defaultdict(int)

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
    query = Q(team_id=team_id, saved_query_id=model_id)
    paths = DataWarehouseModelPath.objects.filter(query)

    dag: dict[str, list[Any]] = {"nodes": [], "edges": []}
    seen_nodes: set[str] = set()
    uuid_nodes: set[uuid.UUID] = set()
    node_data: dict[str, dict] = {}

    for path in paths:
        components = path.path if isinstance(path.path, list) else path.path.split(".")
        components = join_components_greedily(components)
        for component in components:
            try:
                component_uuid = uuid.UUID(component)
                uuid_nodes.add(component_uuid)
            except ValueError:
                continue

    saved_queries = {str(q.id): q for q in DataWarehouseSavedQuery.objects.filter(id__in=uuid_nodes)}

    for path in paths:
        components = path.path if isinstance(path.path, list) else path.path.split(".")
        components = join_components_greedily(components)
        for i, component in enumerate(components):
            node_id = component
            if node_id not in seen_nodes:
                seen_nodes.add(node_id)
                node_uuid: Optional[uuid.UUID] = None
                saved_query = None
                try:
                    node_uuid = uuid.UUID(component)
                    saved_query = saved_queries.get(str(node_uuid))
                    name = saved_query.name if saved_query else component
                except ValueError:
                    name = component
                node_data[node_id] = {
                    "id": node_id,
                    "type": "view" if node_uuid else "table",
                    "name": name,
                    "sync_frequency": saved_query.sync_frequency_interval if saved_query else None,
                    "last_run_at": saved_query.last_run_at if saved_query else None,
                    "status": saved_query.status if saved_query else None,
                }
            if i > 0:
                source = components[i - 1]
                target = component
                edge = {"source": source, "target": target}
                if edge not in dag["edges"]:
                    dag["edges"].append(edge)

    # Order nodes by execution priority
    ordered_nodes = topological_sort(list(node_data.keys()), dag["edges"])
    dag["nodes"] = [node_data[node_id] for node_id in ordered_nodes]

    return dag
