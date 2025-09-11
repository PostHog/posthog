from rest_framework import request, response, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.warehouse.models import DataWarehouseModelPath


class DataWarehouseModelPathSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DataWarehouseModelPath


class DataWarehouseModelPathViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"

    queryset = DataWarehouseModelPath.objects.all()
    serializer_class = DataWarehouseModelPathSerializer


class DataWarehouseModelDagViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    def list(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Return this team's DAG as a set of edges and nodes"""
        dag = DataWarehouseModelPath.objects.get_dag(self.team)

        return response.Response({"edges": dag.edges, "nodes": dag.nodes})
