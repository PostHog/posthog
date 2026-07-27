from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField

from products.data_warehouse.backend.presentation.views.column_annotation_base import (
    BaseColumnAnnotationSerializer,
    BaseColumnAnnotationViewSet,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, WarehouseColumnAnnotation


class WarehouseColumnAnnotationSerializer(BaseColumnAnnotationSerializer):
    parent_field_name = "table"

    # Team-scoped so a table PK from another team never resolves — auto-scopes from serializer context.
    table = TeamScopedPrimaryKeyRelatedField(
        queryset=DataWarehouseTable.objects.all(),
        help_text="ID of the data warehouse table this annotation describes.",
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


class WarehouseColumnAnnotationViewSet(BaseColumnAnnotationViewSet):
    """Read and edit semantic descriptions of warehouse tables and columns surfaced to the AI agent.

    List can be filtered to one table with `?table_id=<uuid>`. Any create or update is treated as a
    user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
    enrichment. Create upserts on `(table, column_name)`; the table cannot be changed after creation.
    """

    # Annotations describe `DataWarehouseTable` rows, so they live under the warehouse table family.
    scope_object = "warehouse_table"
    # `.unscoped()` is import-safe (the fail-closed manager raises on `.all()` without team context);
    # the mixin scopes every request by team_id via the parent lookup.
    queryset = WarehouseColumnAnnotation.objects.unscoped()
    serializer_class = WarehouseColumnAnnotationSerializer

    parent_model = DataWarehouseTable
    parent_field_name = "table"
    parent_query_param = "table_id"

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
