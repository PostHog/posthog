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

        paths = DataWarehouseModelPath.objects.filter(query)

        # Build DAG structure
        dag = {"nodes": [], "edges": []}

        # Track unique nodes
        seen_nodes = set()

        # Get all saved query IDs from paths
        saved_query_ids = set()
        for path in paths:
            if isinstance(path.path, list):
                components = path.path
            else:
                components = path.path.split(".")
            saved_query_ids.update([c for c in components if c not in ["postgres", "supabase", "sharks_person"]])

        # Fetch all saved queries in one query
        saved_queries = {str(q.id): q.name for q in DataWarehouseSavedQuery.objects.filter(id__in=saved_query_ids)}

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
                    node_name = saved_queries.get(component, component) if node_type == "saved_query" else component
                    dag["nodes"].append({"id": node_id, "type": node_type, "name": node_name})

                # Add edges
                if i > 0:
                    source = components[i - 1]
                    target = component
                    edge = {"source": source, "target": target}
                    if edge not in dag["edges"]:
                        dag["edges"].append(edge)

        return Response(dag)

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

        # print("\n=== PATHS ===")
        # for path in paths:
        #     print(f"Path: {path.path}")
        #     print(f"Team: {path.team}")
        #     print(f"Saved Query ID: {path.saved_query_id}")
        #     print(f"Table ID: {path.table_id}")
        #     print("---")
        # print("=== END PATHS ===\n")

        # Build DAG structure
        dag = {"nodes": [], "edges": []}

        # Track unique nodes
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
                        name = DataWarehouseSavedQuery.objects.get(id=uuid_obj).name
                    except (ValueError, DataWarehouseSavedQuery.DoesNotExist):
                        name = component
                    dag["nodes"].append({"id": node_id, "type": node_type, "name": name})

                # Add edges
                if i > 0:
                    source = components[i - 1]
                    target = component
                    edge = {"source": source, "target": target}
                    if edge not in dag["edges"]:
                        dag["edges"].append(edge)

        return Response(dag)
