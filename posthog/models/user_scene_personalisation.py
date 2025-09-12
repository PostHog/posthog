from django.db import models

from posthog.models.utils import RootTeamMixin, UUIDTModel


class UserScenePersonalisation(UUIDTModel, RootTeamMixin):
    scene = models.CharField(max_length=200)
    dashboard = models.ForeignKey("Dashboard", on_delete=models.CASCADE, null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE, null=True, blank=True)
    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="scene_personalisation",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user", "scene"],
                name="posthog_unique_scene_personalisation",
            )
        ]
