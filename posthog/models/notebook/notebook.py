from django.db.models import JSONField
from django.utils import timezone

from django.db import models

from posthog.models.utils import UUIDModel
from posthog.utils import generate_short_id


class Notebook(UUIDModel):
    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    title = models.CharField(max_length=256, blank=True, null=True)
    content: JSONField = JSONField(default=None, null=True, blank=True)
    text_content = models.TextField(blank=True, null=True)
    deleted = models.BooleanField(default=False)
    version = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_notebooks",
    )

    class Meta:
        unique_together = ("team", "short_id")
