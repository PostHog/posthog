import secrets

from django.db import models


PUBLIC_ACCESS_TOKEN_EXP_DAYS = 365


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
        max_length=400, null=True, blank=True, default=get_default_access_token
    )
