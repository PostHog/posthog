from posthog.models.utils import UUIDModel, CreatedMetaFields, sane_repr
from django.db import models
from posthog.models.team import Team
from posthog.warehouse.models import ExternalDataSource


class ExternalDataJob(CreatedMetaFields, UUIDModel):

    class Type(models.TextChoices):
        RUNNING = "Running", "Running"
        FAILED = "Failed", "Failed"
        SUCCESS = "Success", "Success"

    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    pipeline: models.ForeignKey = models.ForeignKey(ExternalDataSource, on_delete=models.CASCADE)
    status: models.CharField = models.CharField(max_length=400)
    rows_synced: models.BigIntegerField = models.BigIntegerField(null=True, blank=True)

    __repr__ = sane_repr("id")
