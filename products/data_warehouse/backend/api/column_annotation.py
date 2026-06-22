from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField

from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class WarehouseColumnAnnotationSerializer(serializers.ModelSerializer):
    # Team-scoped so a table PK from another team never resolves — auto-scopes from serializer context.
    table = TeamScopedPrimaryKeyRelatedField(
        queryset=DataWarehouseTable.objects.all(),
        help_text="ID of the data warehouse table this annotation describes.",
    )
    column_name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Column this annotation describes. Empty string denotes the table-level description.",
    )
    description = serializers.CharField(help_text="Human-readable description of what this table or column means.")
    description_source = serializers.ChoiceField(
        choices=WarehouseColumnAnnotation.DescriptionSource.choices,
        read_only=True,
        help_text=(
            "Where the description came from: native_comment (the source database's own column comment), "
            "ai_generated (drafted by an LLM), or user_edited (written or edited by a user)."
        ),
    )
    ai_model = serializers.CharField(
        read_only=True, help_text="Model used when the description was AI-generated, otherwise null."
    )
    is_user_edited = serializers.BooleanField(
        read_only=True, help_text="True once a user has edited this annotation; such rows are never overwritten."
    )

    class Meta:
        model = WarehouseColumnAnnotation
        fields = [
            "id",
            "table",
            "column_name",
            "description",
            "description_source",
            "ai_model",
            "is_user_edited",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "description_source", "ai_model", "is_user_edited", "created_at", "updated_at"]


class WarehouseColumnAnnotationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Read and edit semantic descriptions of warehouse tables and columns surfaced to the AI agent.

    List can be filtered to one table with `?table_id=<uuid>`. Any create or update is treated as a
    user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
    enrichment.
    """

    # Annotations describe `DataWarehouseTable` rows, so they live under the warehouse table family —
    # both the resource-level scope and the per-object filtering below key off `warehouse_table`.
    scope_object = "warehouse_table"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "destroy"]
    # `.unscoped()` is import-safe (the fail-closed manager raises on `.all()` without team context);
    # the mixin scopes every request by team_id via the parent lookup.
    queryset = WarehouseColumnAnnotation.objects.unscoped()
    serializer_class = WarehouseColumnAnnotationSerializer
    ordering = "column_name"

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="table_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Only return annotations for this data warehouse table.",
            )
        ]
    )
    def list(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        return super().list(request, *args, **kwargs)

    def safely_get_queryset(self, queryset: Any) -> Any:
        # Annotations inherit their table's access: only expose those whose table the user can reach.
        # Applied for every action (not just list), so retrieve/update/destroy on an annotation for an
        # inaccessible table 404s through the queryset rather than slipping past object-level checks.
        accessible_tables = self.user_access_control.filter_queryset_by_access_level(
            DataWarehouseTable.objects.filter(team_id=self.team_id)
        )
        queryset = queryset.filter(table__in=accessible_tables)
        table_id = self.request.query_params.get("table_id")
        if table_id:
            queryset = queryset.filter(table_id=table_id)
        return queryset.order_by(self.ordering)

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(
            team_id=self.team_id,
            description_source=WarehouseColumnAnnotation.DescriptionSource.USER_EDITED,
            is_user_edited=True,
        )

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(
            description_source=WarehouseColumnAnnotation.DescriptionSource.USER_EDITED,
            is_user_edited=True,
        )
