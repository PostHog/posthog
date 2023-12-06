from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel, sane_repr


class ExternalDataSchema(CreatedMetaFields, UUIDModel):
    name: models.CharField = models.CharField(max_length=400)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    source: models.ForeignKey = models.ForeignKey(
        "posthog.ExternalDataSource", related_name="schemas", on_delete=models.CASCADE
    )
    table: models.ForeignKey = models.ForeignKey(
        "posthog.DataWarehouseTable", on_delete=models.CASCADE, null=True, blank=True
    )
    should_sync: models.BooleanField = models.BooleanField(default=True)
    latest_error: models.TextField = models.TextField(
        null=True, help_text="The latest error that occurred when syncing this schema."
    )

    __repr__ = sane_repr("name")
