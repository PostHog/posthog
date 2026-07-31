from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr

from products.warehouse_sources.backend.facade.models import WarehouseColumnAnnotation


class DataWarehouseSavedQueryColumnAnnotation(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """Semantic description of a data warehouse saved query (view) or one of its columns, surfaced to the AI agent.

    One row per (saved_query, column). An empty `column_name` is the view-level annotation. Mirrors
    `WarehouseColumnAnnotation` (for physical tables); a row marked `is_user_edited` is never overwritten
    by automatic enrichment.
    """

    # Reuse the physical-table annotation's provenance enum so the two annotation models never drift.
    DescriptionSource = WarehouseColumnAnnotation.DescriptionSource

    # db_constraint=False on the FKs to hot tables (posthog_team, posthog_user): creating a real FK
    # constraint takes a SHARE ROW EXCLUSIVE lock on the parent, which stalls under write traffic. Team
    # scoping is enforced at the app level by TeamScopedRootMixin. The saved_query FK targets a non-hot
    # table, so it keeps its constraint.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    saved_query = models.ForeignKey(
        "data_modeling.DataWarehouseSavedQuery", on_delete=models.CASCADE, related_name="column_annotations"
    )
    # Empty string = view-level annotation; otherwise the column this describes.
    column_name = models.CharField(max_length=400, blank=True, default="")
    description = models.TextField()
    description_source = models.CharField(max_length=32, choices=DescriptionSource)
    ai_model = models.CharField(max_length=128, null=True, blank=True)
    is_user_edited = models.BooleanField(default=False)

    __repr__ = sane_repr("saved_query_id", "column_name", "description_source")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["saved_query", "column_name"], name="unique_saved_query_column_annotation"),
        ]
