from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.utils import UUIDModel


class YearInPostHog(UUIDModel):
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    version: models.CharField = models.CharField(max_length=40)
    user_id: models.IntegerField = models.IntegerField()
    stats: models.JSONField = models.JSONField(default=dict)
    badges: ArrayField = ArrayField(models.CharField(max_length=80), default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user_id", "version"], name="unique_user_version")]
