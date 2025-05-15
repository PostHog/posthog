from django.db import models
from django.utils import timezone
from posthog.models.team import Team
import uuid


def generate_uuid():
    return str(uuid.uuid4())


class Link(models.Model):
    """
    Links that redirect to a specified destination URL.
    These are used for sharing URLs across the application.
    """

    id = models.CharField(max_length=36, primary_key=True, default=generate_uuid)
    destination = models.URLField(max_length=2048)
    origin_domain = models.CharField(max_length=255)
    origin_key = models.CharField(max_length=255)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    description = models.TextField(null=True, blank=True)
    tags = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "team_id"], name="unique_link_id_per_team")]
        indexes = [
            models.Index(fields=["team_id", "id"]),
            models.Index(fields=["team_id", "created_at"]),
        ]

    def __str__(self):
        return f"{self.id} -> {self.destination}"
