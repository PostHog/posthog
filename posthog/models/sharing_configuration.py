import secrets
from typing import List

from django.db import models


def get_default_access_token() -> str:
    return secrets.token_urlsafe(22)


class SharingConfiguration(models.Model):
    # Relations
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.CASCADE, null=True)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE, null=True)

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)

    enabled: models.BooleanField = models.BooleanField(default=False)
    access_token: models.CharField = models.CharField(
        max_length=400, null=True, blank=True, default=get_default_access_token, unique=True
    )

    def get_connected_insight_ids(self) -> List[int]:
        if self.insight:
            return [self.insight.id]
        elif self.dashboard:
            # Check whether this sharing configuration's dashboard contains this insight
            return list(
                self.dashboard.tiles.exclude(deleted=True, insight__isnull=True, insight__deleted=True).values_list(
                    "insight__id", flat=True
                )
            )
        return []
