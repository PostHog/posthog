from typing import Any

from rest_framework import filters, serializers, viewsets
from rest_framework.pagination import PageNumberPagination

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.models import Edge, Node


class NodeSerializer(serializers.ModelSerializer):
    upstream_count = serializers.SerializerMethodField(read_only=True)
    downstream_count = serializers.SerializerMethodField(read_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Node
        fields = [
            "id",
            "name",
            "type",
            "dag_id",
            "saved_query_id",
            "properties",
            "created_at",
            "updated_at",
            "upstream_count",
            "downstream_count",
            "last_run_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "upstream_count",
            "downstream_count",
            "last_run_at",
        ]

    def get_upstream_count(self, node: Node) -> int:
        return Edge.objects.filter(target=node, team_id=node.team.id).count()

    def get_downstream_count(self, node: Node) -> int:
        return Edge.objects.filter(source=node, team_id=node.team.id).count()

    def get_last_run_at(self, node: Node) -> str:
        return node.properties.get("system", {}).get("last_run_at")


class NodePagination(PageNumberPagination):
    page_size = 100


class NodeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for data modeling nodes.
    """

    scope_object = "INTERNAL"
    queryset = Node.objects.all()
    serializer_class = NodeSerializer
    pagination_class = NodePagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "dag_id"]
    ordering = "-created_at"

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        return context

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).order_by(self.ordering)
