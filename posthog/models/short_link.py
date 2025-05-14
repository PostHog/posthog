from django.db import models
from django.utils import timezone
from posthog.models.team import Team
from posthog.utils import generate_short_id


class ShortLink(models.Model):
    """
    Links that redirect to a specified destination URL.
    These are used for sharing URLs across the application.
    """

    key = models.CharField(max_length=12, primary_key=True, default=generate_short_id)
    hashed_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    destination_url = models.URLField(max_length=2048)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    expiration_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["key", "team_id"], name="unique_short_link_key_per_team")]
        indexes = [
            models.Index(fields=["team_id", "key"]),
            models.Index(fields=["team_id", "created_at"]),
        ]

    def __str__(self):
        return f"{self.key} -> {self.destination_url}"
