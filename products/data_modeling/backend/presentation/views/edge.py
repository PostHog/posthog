from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets

from posthog.api.pagination import FacadePageNumberPagination, facade_numbered_page_response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.utils import strict_fetch
from posthog.paging import Page, PageRequest

from products.data_modeling.backend.facade.api import delete_orphaned_table_nodes, find_edge_id, list_edge_ids
from products.data_modeling.backend.facade.models import Edge, NodeType
from products.data_modeling.backend.presentation.views.metric_visibility import (
    DELETE_DENIED,
    EDIT_DENIED,
    MetricNodeVisibilityMixin,
)
from products.data_modeling.backend.presentation.views.rows import rows_in_id_order

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


class EdgePagination(FacadePageNumberPagination):
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
    queryset = Edge.objects.select_related("dag", "source__saved_query", "target__saved_query").all()
    serializer_class = EdgeSerializer
    pagination_class = EdgePagination
    path_parameters = {"pk": UUID}

    def get_serializer_context(self) -> dict[str, Any]:
        return super().get_serializer_context()

    def get_serializer_class(self) -> type[serializers.Serializer]:
        return EdgeSummarySerializer if self.action == "list" else EdgeSerializer

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._require_warehouse_access(level="editor", message=EDIT_DENIED)
        edge = cast(Edge, serializer.instance)
        self._require_view_edit_access(edge.source.saved_query, edge.target.saved_query)
        serializer.save()

    def perform_destroy(self, instance: Edge) -> None:
        self._require_warehouse_access(level="editor", message=DELETE_DENIED)
        self._require_view_edit_access(instance.source.saved_query, instance.target.saved_query)
        if instance.target.belongs_to_managed_viewset:
            raise serializers.ValidationError("Edges into views PostHog manages cannot be deleted.")
        if _connects_a_metric(instance):
            raise serializers.ValidationError(_METRIC_EDGE_REFUSAL)
        instance.delete()
        delete_orphaned_table_nodes(instance.team_id, [instance.source_id])

    @extend_schema(responses=EdgeSummarySerializer(many=True))
    def list(self, request, *args, **kwargs):
        def fetch(page_request: PageRequest) -> Page[Edge]:
            edge_ids = list_edge_ids(self.team, self.user_access_control, page=page_request)
            return Page(
                results=rows_in_id_order(strict_fetch(Edge.objects.filter(team_id=self.team_id)), edge_ids.results),
                count=edge_ids.count,
            )

        return facade_numbered_page_response(self, fetch)

    def read_object(self) -> Edge | None:
        edge_id = find_edge_id(self.team, self.user_access_control, edge_id=self.kwargs["pk"])
        if edge_id is None:
            return None
        edges = Edge.objects.filter(team_id=self.team_id).select_related(
            "dag", "source__saved_query", "target__saved_query"
        )
        return edges.filter(id=edge_id).first()
