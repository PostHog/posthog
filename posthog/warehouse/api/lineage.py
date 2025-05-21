from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from posthog.warehouse.models.modeling import DataWarehouseModelPath
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework.permissions import IsAuthenticated
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
import uuid


class LineageViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["GET"])
    def get_upstream(self, request, parent_lookup_team_id=None):
        team = request.user.team
        model_id = request.query_params.get("model_id")
        model_type = request.query_params.get("type")

        if not model_id or not model_type:
            return Response({"error": "model_id and type are required"}, status=400)

        query = Q(team=team)
        if model_type == "saved_query":
            query &= Q(saved_query_id=model_id)
        else:
            query &= Q(table_id=model_id)

        paths = DataWarehouseModelPath.objects.filter(query)

        dag = {"nodes": [], "edges": []}

        seen_nodes = set()

        for path in paths:
            if isinstance(path.path, list):
                components = path.path
            else:
                components = path.path.split(".")

            # Add nodes
            for i, component in enumerate(components):
                node_id = component
                if node_id not in seen_nodes:
                    seen_nodes.add(node_id)
                    node_type = "external" if component in ["postgres", "supabase"] else "saved_query"
                    try:
                        uuid_obj = uuid.UUID(component)
                        saved_query = DataWarehouseSavedQuery.objects.get(id=uuid_obj)
                        name = saved_query.name
                    except (ValueError, DataWarehouseSavedQuery.DoesNotExist):
                        name = component
                    dag["nodes"].append(
                        {
                            "id": node_id,
                            "type": node_type,
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
