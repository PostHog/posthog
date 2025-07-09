from django.db import models
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDModel


class Shortlink(UUIDModel):
    """
    Stores shortlinks created via dub.co integration for insight template sharing.
    Each shortlink maps a long template URL to a short dub.co URL for easier sharing.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    original_url = models.TextField(help_text="The original long template URL")
    short_code = models.CharField(max_length=50, help_text="The dub.co shortlink key/code")
    short_url = models.URLField(help_text="The complete dub.co shortlink URL")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "created_at"]),
        ]

    def __str__(self):
        return f"{self.short_code} -> {self.original_url[:50]}..."
