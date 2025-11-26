from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


class ColumnConfiguration(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    context_key = models.CharField(max_length=255, db_index=True)
    columns = ArrayField(models.TextField(), null=False, blank=False, default=list)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "context_key"], name="unique_team_context_key")]
        indexes = [models.Index(fields=["team", "context_key"])]

    def __str__(self):
        return f"ColumnConfig(team={self.team_id}, context={self.context_key})"
