from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils import timezone

from .team import Team


class SessionRecordingEvent(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["team_id", "session_id"]),
            models.Index(fields=["team_id", "distinct_id", "timestamp", "session_id"]),
        ]

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    timestamp: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    distinct_id: models.CharField = models.CharField(max_length=200)
    session_id: models.CharField = models.CharField(max_length=200)
    snapshot_data: JSONField = JSONField(default=dict)
