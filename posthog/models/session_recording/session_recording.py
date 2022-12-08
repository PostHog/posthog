from django.db import models
from django.utils import timezone

from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class SessionRecording(UUIDModel):
    session_id: models.CharField = models.CharField(unique=True, max_length=200)
    description: models.TextField = models.TextField(blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    last_modified_by: models.ForeignKey = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="modified_recordings"
    )
    deleted: models.BooleanField = models.BooleanField(default=False)
    s3_url: models.CharField = models.CharField(max_length=65535, null=True, blank=True)

    # TODO: add metadata field to keep minimal information on this model for quick access
