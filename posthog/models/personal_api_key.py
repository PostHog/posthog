from django.db import models
from django.utils import timezone

from .utils import generate_random_token


class PersonalAPIKey(models.Model):
    id: models.CharField = models.CharField(primary_key=True, max_length=50, default=generate_random_token)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="personal_api_keys")
    label: models.CharField = models.CharField(max_length=40)
    value: models.CharField = models.CharField(
        unique=True, max_length=50, default=generate_random_token, editable=False
    )
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    last_used_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    # DEPRECATED: personal API keys are now specifically personal, without team affiliation
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.SET_NULL, related_name="personal_api_keys+", null=True, blank=True
    )
