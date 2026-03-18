from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel
from posthog.utils import generate_short_id


class WebAnalyticsFilterPreset(UUIDModel):
    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    pinned = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    filters = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_web_analytics_filter_presets",
    )

    LAST_MODIFIED_FIELDS = {"name", "description", "filters"}

    class Meta:
        unique_together = ("team", "short_id")
        indexes = [
            models.Index(fields=["deleted", "-last_modified_at"], name="wa_preset_del_mod_idx"),
        ]
