from django.db import models
from django.utils import timezone

from posthog.models.team import Team


class SessionRecordingEvent(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["team_id", "session_id"]),
            models.Index(fields=["team_id", "distinct_id", "timestamp", "session_id"]),
            # The index below exists but was replaced with SQL to avoid some issues
            # The migration is in 0110, and see https://github.com/PostHog/posthog/issues/4969 for more info
            #   models.Index(fields=["team_id", "timestamp"]),
        ]

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    timestamp: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    distinct_id: models.CharField = models.CharField(max_length=200)
    session_id: models.CharField = models.CharField(max_length=200)
    window_id: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    snapshot_data: models.JSONField = models.JSONField(default=dict)


class SessionRecordingViewed(models.Model):
    class Meta:
        unique_together = (("team_id", "user_id", "session_id"),)
        indexes = [models.Index(fields=["team_id", "user_id", "session_id"])]

    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    user: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    session_id: models.CharField = models.CharField(max_length=200)
