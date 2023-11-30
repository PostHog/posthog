from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel, sane_repr


class ExternalDataJob(CreatedMetaFields, UUIDModel):
    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        FAILED = "Failed", "Failed"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    pipeline: models.ForeignKey = models.ForeignKey("posthog.ExternalDataSource", on_delete=models.CASCADE)
    status: models.CharField = models.CharField(max_length=400)
    rows_synced: models.BigIntegerField = models.BigIntegerField(null=True, blank=True)
    latest_error: models.TextField = models.TextField(
        null=True, help_text="The latest error that occurred during this run."
    )

    __repr__ = sane_repr("id")
