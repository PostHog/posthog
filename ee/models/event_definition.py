import pytz
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from posthog.models.event_definition import EventDefinition


class EnterpriseEventDefinition(EventDefinition):
    owner = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, related_name="event_definitions",)
    description: models.CharField = models.CharField(max_length=400, blank=True)
    tags: ArrayField = ArrayField(models.CharField(max_length=32), null=True, blank=True, default=list)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, blank=True)
    verified: models.BooleanField = models.BooleanField(default=False, null=False, blank=True)
    verified_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        "posthog.User", null=True, on_delete=models.SET_NULL, blank=True, related_name="verifying_user"
    )

    def __init__(self, *args, **kwargs):
        # Update verified_at if verified at initialization
        super().__init__(*args, **kwargs)
        if self.verified:
            self.verified_at = timezone.now()
        self._prev_verified = self.verified

    def save(self, *args, **kwargs):
        # Previously unverified event becomes verified
        if not self._prev_verified and self.verified:
            self.verified_at = timezone.now()
        # Event becomes unverified
        elif not self.verified:
            self.verified_at = None
            self.verified_by = None
        self._prev_verified = self.verified
        super().save(*args, **kwargs)
