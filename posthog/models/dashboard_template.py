from django.db import models

from posthog.models.utils import UUIDModel


class DashboardTemplate(UUIDModel):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    template: models.JSONField = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["key"], name="unique_template_key"),
        ]
