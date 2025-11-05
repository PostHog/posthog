from django.db import models
from django.db.models.expressions import F
from django.utils import timezone

from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import uuid7


class PersistedFolder(models.Model):
    """
    Per-user, per-team persisted folder.

    A single user can have exactly one row of a given `type`
    (home, pinned, …) inside each team.
    """

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    user: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE)

    TYPE_HOME = "home"
    TYPE_PINNED = "pinned"
    type: models.CharField = models.CharField(
        max_length=32,
        choices=[
            (TYPE_HOME, "Home"),
            (TYPE_PINNED, "Pinned"),
        ],
    )

    protocol: models.CharField = models.CharField(max_length=64, default="products://")
    path: models.TextField = models.TextField(blank=True, default="")

    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now, editable=False)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("team", "user", "type"),)
        indexes = [
            models.Index(F("team_id"), F("user_id"), name="posthog_pf_team_user"),
            models.Index(F("team_id"), F("user_id"), F("type"), name="posthog_pf_team_user_type"),
        ]
        verbose_name = "Persisted Folder"
        verbose_name_plural = "Persisted Folders"

    def __str__(self) -> str:
        return f"{self.team_id}:{self.user_id}:{self.type} → {self.protocol}{self.path}"
