from django.db import models
from django.db.models import Q

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr


class ExternalDataSourceProjectionRevision(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    source = models.ForeignKey(
        "data_warehouse.ExternalDataSource",
        on_delete=models.CASCADE,
        related_name="projection_revisions",
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)

    __repr__ = sane_repr("source_id", "version", "is_active")

    class Meta:
        db_table = "posthog_externaldatasourceprojectionrevision"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "version"],
                name="posthog_externaldatasourceprojectionrevision_source_version",
            ),
            models.UniqueConstraint(
                fields=["source"],
                condition=Q(is_active=True),
                name="posthog_externaldatasourceprojectionrevision_one_active_per_source",
            ),
        ]
