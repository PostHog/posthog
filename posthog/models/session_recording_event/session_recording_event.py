import dataclasses
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from django.db import models

from posthog.models.team import Team


class SessionRecordingEventSummary(TypedDict):
    timestamp: int
    is_active: bool
    event_type: int
    source_type: Optional[int]


# NOTE: SessionRecordingEvent is a clickhouse "model"
@dataclasses.dataclass
class SessionRecordingEvent:
    # created_at: datetime  # models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    timestamp: datetime  # models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)
    # team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    distinct_id: str  # models.CharField = models.CharField(max_length=200)
    session_id: str  # models.CharField = models.CharField(max_length=200)
    window_id: str  # models.CharField = models.CharField(max_length=200, null=True, blank=True)
    snapshot_data: Dict[str, Any]  # models.JSONField = models.JSONField(default=dict)
    # Can be optional as this was added later
    events_summary: Optional[List[SessionRecordingEventSummary]]  # models.JSONField = models.JSONField(default=dict)


class SessionRecordingViewed(models.Model):
    class Meta:
        unique_together = (("team_id", "user_id", "session_id"),)
        indexes = [models.Index(fields=["team_id", "user_id", "session_id"])]

    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    user: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    session_id: models.CharField = models.CharField(max_length=200)
