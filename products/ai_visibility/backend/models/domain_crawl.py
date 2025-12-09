import uuid

from django.db import models
from django.utils import timezone


class AiVisibilityRun(models.Model):
    """Tracks runs of a temporal workflow that crawls a domain for AI visibility."""

    class Status(models.TextChoices):
        READY = "ready", "Ready"
        RUNNING = "running", "Running"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.CharField(max_length=255, db_index=True)
    workflow_id = models.CharField(
        max_length=255,
        help_text="Temporal workflow ID for this run",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    error_message = models.TextField(
        blank=True,
        null=True,
        help_text="Error message if the run failed",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    completed_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp when the run completed or failed",
    )

    class Meta:
        db_table = "posthog_ai_visibility_run"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["domain", "-created_at"]),
        ]

    def __str__(self):
        return f"AiVisibilityRun({self.domain}, {self.status})"

    @classmethod
    def get_latest_for_domain(cls, domain: str) -> "AiVisibilityRun | None":
        """Get the most recent run for a domain."""
        return cls.objects.filter(domain=domain).first()

    def mark_ready(self):
        """Mark the run as ready (completed successfully)."""
        self.status = self.Status.READY
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])

    def mark_failed(self, error: str):
        """Mark the run as failed with an error message."""
        self.status = self.Status.FAILED
        self.error_message = error
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at"])
