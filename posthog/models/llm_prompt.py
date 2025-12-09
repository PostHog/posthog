from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


class LLMPrompt(UUIDModel):
    name = models.CharField(max_length=255)

    # The prompt content as JSON (currently a string, may expand to array of objects)
    prompt = models.JSONField()

    # TODO: Auto-increment version on updates when versioning feature is implemented
    version = models.PositiveIntegerField(default=1)

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    deleted = models.BooleanField(default=False)
