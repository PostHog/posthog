from typing import Any

from rest_framework import filters, serializers, viewsets
from rest_framework.pagination import PageNumberPagination

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.models import Edge


class EdgeSerializer(serializers.ModelSerializer):
    source_id = serializers.UUIDField(source="source.id", read_only=True)
    target_id = serializers.UUIDField(source="target.id", read_only=True)

    class Meta:
        model = Edge
        fields = [
            "id",
            "source_id",
            "target_id",
            "dag_id",
            "properties",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]


class EdgePagination(PageNumberPagination):
    page_size = 500


class EdgeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = Edge.objects.all()
    serializer_class = EdgeSerializer
    pagination_class = EdgePagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["dag_id"]
    ordering = "-created_at"

    def get_serializer_context(self) -> dict[str, Any]:
        return super().get_serializer_context()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).order_by(self.ordering)
