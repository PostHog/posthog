from typing import Any
from uuid import UUID

from rest_framework import filters, serializers, viewsets
from rest_framework.pagination import PageNumberPagination

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.facade.models import Edge


class EdgeSerializer(serializers.ModelSerializer):
    source_id = serializers.UUIDField(source="source.id", read_only=True)
    target_id = serializers.UUIDField(source="target.id", read_only=True)
    dag_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Edge
        fields = [
            "id",
            "source_id",
            "target_id",
            "dag",
            "dag_name",
            "properties",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "dag_name",
            "created_at",
            "updated_at",
        ]

    def get_dag_name(self, edge: Edge) -> str:
        return edge.dag.name

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # System-managed DAGs (e.g. Revenue Analytics) own their edges; the internal sync path
        # maintains them directly via the ORM and bypasses this serializer. Block users from
        # editing managed edges or moving any edge into a managed DAG via the API.
        if self.instance is not None and self.instance.dag.is_managed:
            raise serializers.ValidationError("Edges belonging to a system-managed DAG cannot be modified.")
        target_dag = attrs.get("dag")
        if target_dag is not None and target_dag.is_managed:
            raise serializers.ValidationError("Edges cannot be created in or moved into a system-managed DAG.")
        return attrs


class EdgePagination(PageNumberPagination):
    page_size = 5000


class EdgeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = Edge.objects.select_related("dag").all()
    serializer_class = EdgeSerializer
    pagination_class = EdgePagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["dag__name"]
    ordering = "-created_at"

    def get_serializer_context(self) -> dict[str, Any]:
        return super().get_serializer_context()

    def perform_destroy(self, instance: Edge) -> None:
        if instance.dag.is_managed:
            raise serializers.ValidationError("Edges belonging to a system-managed DAG cannot be deleted.")
        instance.delete()

    def safely_get_queryset(self, queryset):
        qs = queryset.filter(team_id=self.team_id)
        dag_id = self.request.query_params.get("dag")
        if dag_id:
            try:
                UUID(dag_id)
            except ValueError:
                dag_id = None
            else:
                qs = qs.filter(dag_id=dag_id)
        return qs.order_by(self.ordering)
