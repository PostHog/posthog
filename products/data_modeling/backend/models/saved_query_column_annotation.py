from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr


class SavedQueryColumnAnnotation(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """Semantic description of a data warehouse saved query (view) or one of its columns, surfaced to the AI agent.

    One row per (saved_query, column). An empty `column_name` is the view-level annotation. Mirrors
    `WarehouseColumnAnnotation` (for physical tables); a row marked `is_user_edited` is never overwritten
    by automatic enrichment.
    """

    class DescriptionSource(models.TextChoices):
        CANONICAL = "canonical", "Canonical"
        AI_GENERATED = "ai_generated", "AI generated"
        USER_EDITED = "user_edited", "User edited"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
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
