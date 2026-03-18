from django.db import models

from posthog.models.utils import RootTeamMixin, UUIDTModel


class UserHomeSettings(UUIDTModel, RootTeamMixin):
    """Stores personalized navigation settings such as pinned tabs and the homepage for a user within a team."""

    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="home_settings",
        null=True,
        blank=True,
    )
    team = models.ForeignKey("Team", on_delete=models.CASCADE, null=True, blank=True)
    tabs = models.JSONField(default=list, blank=True)
    homepage = models.JSONField(default=dict, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user"],
                name="posthog_unique_user_home_settings",
            )
        ]
