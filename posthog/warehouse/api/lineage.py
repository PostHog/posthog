from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from posthog.warehouse.models.modeling import DataWarehouseModelPath
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework.permissions import IsAuthenticated


class LineageViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["GET"])
    def get_lineage(self, request, parent_lookup_team_id=None):
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

        # Get all paths for this model
        paths = DataWarehouseModelPath.objects.filter(query)

        # Build lineage graph
        lineage = {"nodes": [], "edges": []}

        for path in paths:
            # Split path into components
            components = path.path.split(".")

            # Add nodes
            for i, component in enumerate(components):
                node_id = f"{component}_{i}"
                if not any(n["id"] == node_id for n in lineage["nodes"]):
                    lineage["nodes"].append(
                        {
                            "id": node_id,
                            "name": component,
                            "type": "root" if i == 0 else "intermediate" if i < len(components) - 1 else "leaf",
                        }
                    )

                # Add edges
                if i > 0:
                    prev_node_id = f"{components[i-1]}_{i-1}"
                    lineage["edges"].append({"source": prev_node_id, "target": node_id})

        return Response(lineage)

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

        upstream = set()
        for path in paths:
            if isinstance(path.path, str):
                components = path.path.split(".")
                if len(components) > 1:
                    upstream.add(components[0])  # First component is always upstream

        return Response(list(upstream))
