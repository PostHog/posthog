from datetime import timedelta

from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


class ExportedRecording(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="exported_recordings")
    session_id = models.CharField(max_length=200)
    reason = models.TextField()
    export_location = models.CharField(max_length=1000, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exported_recordings",
    )

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_expired(self) -> bool:
        return self.created_at < timezone.now() - timedelta(days=7)

    def __str__(self):
        return f"ExportedRecording({self.session_id}, {self.status})"
