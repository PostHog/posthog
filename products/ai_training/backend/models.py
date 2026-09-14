from django.db import models
from django.utils import timezone

from posthog.models.scoping.manager import EnvironmentScopedManager
from posthog.models.utils import uuid7


class AITrainingConsent(models.Model):
    organization_id = models.UUIDField(primary_key=True)
    allowed = models.BooleanField(default=False)
    granted_at_ms = models.BigIntegerField(default=0)
    changed_at_ms = models.BigIntegerField(default=0)
    revision = models.BigIntegerField(default=0)

    class Meta:
        db_table = "posthog_aitrainingconsent"


class AITrainingPrivacyRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization_id = models.UUIDField(null=True)
    team_id = models.BigIntegerField(null=True)
    kind = models.CharField(max_length=32)
    identifiers = models.JSONField(default=list)
    allowed = models.BooleanField(null=True)
    granted_at_ms = models.BigIntegerField(default=0)
    changed_at_ms = models.BigIntegerField(default=0)
    revision = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    leased_until = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True)
    cursor = models.JSONField(default=dict)

    all_teams = models.Manager()
    objects = EnvironmentScopedManager()

    class Meta:
        db_table = "posthog_aitrainingprivacyrequest"
        default_manager_name = "all_teams"
        indexes = [
            models.Index(
                fields=["created_at"],
                condition=models.Q(completed_at__isnull=True),
                name="ai_training_pending_requests",
            )
        ]
