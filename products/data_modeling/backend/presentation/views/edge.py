from typing import Any

from rest_framework import mixins, serializers, viewsets
from rest_framework.pagination import PageNumberPagination

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.facade.api import delete_orphaned_table_nodes
from products.data_modeling.backend.facade.models import Edge, NodeType
from products.data_modeling.backend.presentation.views.metric_visibility import DELETE_DENIED, MetricNodeVisibilityMixin

_METRIC_EDGE_REFUSAL = "Edges that connect a metric are maintained by the data catalog."


def _connects_a_metric(edge: Edge) -> bool:
    return NodeType.METRIC in (edge.source.type, edge.target.type)


class EdgeSerializer(serializers.ModelSerializer):
    source_id = serializers.UUIDField(read_only=True, help_text="ID of the upstream node.")
    target_id = serializers.UUIDField(read_only=True, help_text="ID of the downstream node.")

    class Meta:
        model = Edge
        fields = [
            "id",
            "source_id",
            "target_id",
            "properties",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Managed viewsets (e.g. Revenue Analytics) own the edges into their views; the internal
        # sync path maintains them directly via the ORM and bypasses this serializer. Block users
        # from editing those edges via the API.
        if self.instance is not None and self.instance.target.belongs_to_managed_viewset:
            raise serializers.ValidationError("Edges into views PostHog manages cannot be modified.")
        if self.instance is not None and _connects_a_metric(self.instance):
            raise serializers.ValidationError(_METRIC_EDGE_REFUSAL)
        return attrs


class EdgeSummarySerializer(serializers.ModelSerializer):
    source_id = serializers.UUIDField(read_only=True, help_text="ID of the upstream node.")
    target_id = serializers.UUIDField(read_only=True, help_text="ID of the downstream node.")

    class Meta:
        model = Edge
        fields = ["id", "source_id", "target_id"]
        read_only_fields = fields


class EdgePagination(PageNumberPagination):
    page_size = 5000


class EdgeViewSet(
    MetricNodeVisibilityMixin,
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    queryset = Edge.objects.select_related("dag", "target__saved_query").all()
    serializer_class = EdgeSerializer
    pagination_class = EdgePagination
    ordering = "-created_at"

    def get_serializer_context(self) -> dict[str, Any]:
        return super().get_serializer_context()

    def get_serializer_class(self) -> type[serializers.Serializer]:
        return EdgeSummarySerializer if self.action == "list" else EdgeSerializer

    def perform_destroy(self, instance: Edge) -> None:
        self._require_warehouse_access(level="editor", message=DELETE_DENIED)
        if instance.target.belongs_to_managed_viewset:
            raise serializers.ValidationError("Edges into views PostHog manages cannot be deleted.")
        if _connects_a_metric(instance):
            raise serializers.ValidationError(_METRIC_EDGE_REFUSAL)
        instance.delete()
        delete_orphaned_table_nodes(instance.team_id, [instance.source_id])

    def safely_get_queryset(self, queryset):
        if self.action == "list":
            queryset = queryset.select_related(None)
        return self._exclude_hidden_edges(queryset.filter(team_id=self.team_id)).order_by(self.ordering)
