from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


class ColumnConfiguration(UUIDModel):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private (only visible to creator)"
        SHARED = "shared", "Shared with team"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=255, default="Column configuration")
    context_key = models.CharField(max_length=255, db_index=True)
    columns = ArrayField(models.TextField(), null=False, blank=False, default=list)
    filters = models.JSONField(default=dict, null=True, blank=True)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.SHARED)

    created_by = models.ForeignKey("posthog.User", on_delete=models.CASCADE, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "context_key", "name", "created_by"],
                name="unique_user_view_name",
                condition=models.Q(visibility="private"),
            ),
            models.UniqueConstraint(
                fields=["team", "context_key", "name"],
                name="unique_team_view_name",
                condition=models.Q(visibility="shared"),
            ),
        ]
        indexes = [models.Index(fields=["team", "context_key"])]

    def __str__(self):
        if self.name:
            return f"ColumnConfig(team={self.team_id}, context={self.context_key}, name={self.name})"
        return f"ColumnConfig(team={self.team_id}, context={self.context_key})"
