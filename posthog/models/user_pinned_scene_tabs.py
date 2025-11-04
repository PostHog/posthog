from django.db import models

from posthog.models.utils import RootTeamMixin, UUIDTModel


class UserPinnedSceneTabs(UUIDTModel, RootTeamMixin):
    """Stores the pinned scene tabs for a user within a team."""

    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="pinned_scene_tabs",
        null=True,
        blank=True,
    )
    team = models.ForeignKey("Team", on_delete=models.CASCADE, null=True, blank=True)
    tabs = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user"],
                name="posthog_unique_user_pinned_scene_tabs",
            )
        ]
