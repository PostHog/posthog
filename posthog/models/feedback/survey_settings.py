from django.db import models

from posthog.models.utils import UUIDModel


class SurveySettings(UUIDModel):
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="survey_settings",
        related_query_name="survey_settings",
    )

    appearance = models.JSONField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
