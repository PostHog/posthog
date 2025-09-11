from django.db import models
from django.db.models.expressions import F
from django.utils import timezone

from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import uuid7


class FileSystemShortcut(models.Model):
    """
    A model representing a "file" (or folder) in our hierarchical system.
    """

    id = models.UUIDField(primary_key=True, default=uuid7)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    path = models.TextField()
    type = models.CharField(max_length=100, blank=True)
    ref = models.CharField(max_length=100, null=True, blank=True)
    href = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        indexes = [
            models.Index(fields=["team", "user"]),
            models.Index(F("team_id"), F("path"), name="posthog_fs_s_team_path"),
            models.Index(F("team_id"), F("type"), F("ref"), name="posthog_fs_s_team_typeref"),
        ]

    def __str__(self):
        return self.path
