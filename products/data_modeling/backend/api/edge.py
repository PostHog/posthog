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
            "dag_fk",
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
    page_size = 5000


class EdgeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = Edge.objects.all()
    serializer_class = EdgeSerializer
    pagination_class = EdgePagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["dag_fk__name"]
    ordering = "-created_at"

    def get_serializer_context(self) -> dict[str, Any]:
        return super().get_serializer_context()

    def safely_get_queryset(self, queryset):
        # TODO(andrew): remove the dag name filter after you have split up team 2 into multiple DAGs
        return queryset.filter(team_id=self.team_id, dag_fk__name=f"posthog_{self.team_id}").order_by(self.ordering)
