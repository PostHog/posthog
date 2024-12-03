import secrets
from typing import cast

from django.db import models

from posthog.models.insight import Insight


def get_default_access_token() -> str:
    return secrets.token_urlsafe(22)


class SharingConfiguration(models.Model):
    # Relations
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.CASCADE, null=True)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE, null=True)
    recording = models.ForeignKey(
        "SessionRecording",
        related_name="sharing_configurations",
        on_delete=models.CASCADE,
        to_field="session_id",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    enabled = models.BooleanField(default=False)
    access_token = models.CharField(
        max_length=400,
        null=True,
        blank=True,
        default=get_default_access_token,
        unique=True,
    )

    def can_access_object(self, obj: models.Model):
        if obj.team_id != self.team_id:  # type: ignore
            return False

        if obj._meta.object_name == "Insight" and self.dashboard:
            return cast(Insight, obj).id in self.get_connected_insight_ids()

        for comparison in [self.insight, self.dashboard, self.recording]:
            if comparison and comparison == obj:
                return True

        return False

    def get_connected_insight_ids(self) -> list[int]:
        if self.insight:
            if self.insight.deleted:
                return []
            return [self.insight.id]
        elif self.dashboard:
            if self.dashboard.deleted:
                return []
            # Check whether this sharing configuration's dashboard contains this insight
            return list(self.dashboard.tiles.exclude(insight__deleted=True).values_list("insight__id", flat=True))
        return []
