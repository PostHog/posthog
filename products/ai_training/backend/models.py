from django.db import models
from django.utils import timezone

from posthog.models.scoping.manager import EnvironmentScopedManager
from posthog.models.utils import uuid7


class AITrainingDeletionRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team_id = models.BigIntegerField()
    kind = models.CharField(max_length=32)
    identifiers = models.JSONField(default=list)
    created_at = models.DateTimeField(default=timezone.now)
    leased_until = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True)
    cursor = models.JSONField(default=dict)

    all_teams = models.Manager()
    objects = EnvironmentScopedManager()

    class Meta:
        db_table = "posthog_aitrainingdeletionrequest"
        default_manager_name = "all_teams"
        indexes = [
            models.Index(
                fields=["created_at"],
                condition=models.Q(completed_at__isnull=True),
                name="ai_training_pending_requests",
            )
        ]
