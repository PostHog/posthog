from drf_spectacular.utils import extend_schema_field
from rest_framework import request, response, serializers, viewsets

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.data_warehouse.backend.models import DataWarehouseModelPath


class DataWarehouseModelPathSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    path = serializers.SerializerMethodField()

    @extend_schema_field({"type": "array", "items": {"type": "string"}})
    def get_path(self, obj) -> list[str]:
        return obj.path or []

    class Meta:
        model = DataWarehouseModelPath
        fields = ["id", "path", "team", "table", "saved_query", "created_at", "created_by", "updated_at"]


class DataWarehouseModelPathViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"

    queryset = DataWarehouseModelPath.objects.all()
    serializer_class = DataWarehouseModelPathSerializer


class DataWarehouseModelDagViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer

    def list(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Return this team's DAG as a set of edges and nodes"""
        dag = DataWarehouseModelPath.objects.get_dag(self.team)

        return response.Response({"edges": dag.edges, "nodes": dag.nodes})
