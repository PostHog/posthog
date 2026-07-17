from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField

from products.data_modeling.backend.facade.models import (
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryColumnAnnotation,
)
from products.data_warehouse.backend.presentation.views.column_annotation_base import (
    BaseColumnAnnotationSerializer,
    BaseColumnAnnotationViewSet,
)


class DataWarehouseSavedQueryColumnAnnotationSerializer(BaseColumnAnnotationSerializer):
    parent_field_name = "saved_query"

    # Team-scoped so a saved-query PK from another team never resolves — auto-scopes from serializer context.
    # Excludes deleted views so create can't annotate one (the viewset queryset covers the read/update paths).
    saved_query = TeamScopedPrimaryKeyRelatedField(
        queryset=DataWarehouseSavedQuery.objects.exclude(deleted=True),
        help_text="ID of the data warehouse saved query (view) this annotation describes.",
    )

    class Meta:
        model = DataWarehouseSavedQueryColumnAnnotation
        fields = [
            "id",
            "saved_query",
            "column_name",
            "description",
            "description_source",
            "ai_model",
            "is_user_edited",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "description_source", "ai_model", "is_user_edited", "created_at", "updated_at"]


class DataWarehouseSavedQueryColumnAnnotationViewSet(BaseColumnAnnotationViewSet):
    """Read and edit semantic descriptions of data-modelling views and columns surfaced to the AI agent.

    List can be filtered to one view with `?saved_query_id=<uuid>`. Any create or update is treated as a
    user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
    enrichment. Create upserts on `(saved_query, column_name)`; the view cannot be changed after creation.
    """

    scope_object = "warehouse_view"
    # `.unscoped()` is import-safe (the fail-closed manager raises on `.all()` without team context);
    # the mixin scopes every request by team_id via the parent lookup.
    queryset = DataWarehouseSavedQueryColumnAnnotation.objects.unscoped()
    serializer_class = DataWarehouseSavedQueryColumnAnnotationSerializer

    parent_model = DataWarehouseSavedQuery
    parent_field_name = "saved_query"
    parent_query_param = "saved_query_id"

    def _filter_parent_queryset(self, queryset: Any) -> Any:
        # Never annotate a deleted view. Endpoint-origin and other accessible views ARE annotatable —
        # descriptions help the AI, and hiding endpoints from the list view is a UI concern, not an
        # access boundary.
        return queryset.exclude(deleted=True)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="saved_query_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Only return annotations for this data warehouse saved query (view).",
            )
        ]
    )
    def list(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        return super().list(request, *args, **kwargs)
