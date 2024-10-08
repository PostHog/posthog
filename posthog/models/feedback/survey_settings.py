from django.db import models

from posthog.models.utils import UUIDModel


class SurveySettings(UUIDModel):
    team = models.OneToOneField(
        "Team", on_delete=models.SET_NULL, blank=True, null=True, related_name="survey_settings"
    )
    appearance = models.JSONField(blank=True, null=True)
    templates = models.JSONField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
