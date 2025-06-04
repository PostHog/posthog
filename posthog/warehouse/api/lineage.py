from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from posthog.warehouse.models.modeling import DataWarehouseModelPath
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework.permissions import IsAuthenticated
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
import uuid


def join_components_greedily(components):
    """
    Greedily joins components until hitting a UUID.
    Returns a list where UUIDs are separate items and non-UUID components are joined.
    """
    new_components = []
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

        query = Q(team_id=self.team_id, saved_query_id=model_id)

        paths = DataWarehouseModelPath.objects.filter(query)

        dag: dict[str, list] = {"nodes": [], "edges": []}

        seen_nodes = set()
        uuid_nodes = set()

        for path in paths:
            if isinstance(path.path, list):
                components = path.path
            else:
                components = path.path.split(".")

            components = join_components_greedily(components)

            for component in components:
                try:
                    uuid_obj = uuid.UUID(component)
                    uuid_nodes.add(uuid_obj)
                except ValueError:
                    continue

        saved_queries = {str(query.id): query for query in DataWarehouseSavedQuery.objects.filter(id__in=uuid_nodes)}

        for path in paths:
            if isinstance(path.path, list):
                components = path.path
            else:
                components = path.path.split(".")

            components = join_components_greedily(components)

            for i, component in enumerate(components):
                node_id = component
                if node_id not in seen_nodes:
                    seen_nodes.add(node_id)
                    uuid_obj = None
                    saved_query = None
                    try:
                        uuid_obj = uuid.UUID(component)
                        saved_query = saved_queries.get(str(uuid_obj))
                        name = saved_query.name if saved_query else component
                    except ValueError:
                        name = component

                    dag["nodes"].append(
                        {
                            "id": node_id,
                            "type": "view" if uuid_obj else "table",
                            "name": name,
                            "sync_frequency": saved_query.sync_frequency_interval if saved_query else None,
                            "last_run_at": saved_query.last_run_at if saved_query else None,
                            "status": saved_query.status if saved_query else None,
                        }
                    )

                if i > 0:
                    source = components[i - 1]
                    target = component
                    edge = {"source": source, "target": target}
                    if edge not in dag["edges"]:
                        dag["edges"].append(edge)

        return Response(dag)
