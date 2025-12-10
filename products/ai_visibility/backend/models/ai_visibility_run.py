import uuid

from django.db import models
from django.utils import timezone


class AiVisibilityRun(models.Model):
    """Tracks runs of a temporal workflow that crawls a domain for AI visibility."""

    class Status(models.TextChoices):
        READY = "ready", "Ready"
        RUNNING = "running", "Running"
        FAILED = "failed", "Failed"

    class ProgressStep(models.TextChoices):
        STARTING = "starting", "Starting"
        EXTRACTING_INFO = "extracting_info", "Extracting business info"
        GENERATING_TOPICS = "generating_topics", "Generating topics"
        GENERATING_PROMPTS = "generating_prompts", "Generating prompts"
        RUNNING_AI_CALLS = "running_ai_calls", "Running AI calls"
        COMBINING_RESULTS = "combining_results", "Combining results"
        SAVING = "saving", "Saving results"
        COMPLETE = "complete", "Complete"

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
    progress_step = models.CharField(
        max_length=30,
        choices=ProgressStep.choices,
        default=ProgressStep.STARTING,
        help_text="Current step in the workflow for progress tracking",
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
    s3_path = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="S3 path where the results are stored",
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

    def mark_ready(self, s3_path: str | None = None):
        """Mark the run as ready (completed successfully)."""
        self.status = self.Status.READY
        self.progress_step = self.ProgressStep.COMPLETE
        self.completed_at = timezone.now()
        update_fields = ["status", "progress_step", "completed_at"]
        if s3_path:
            self.s3_path = s3_path
            update_fields.append("s3_path")
        self.save(update_fields=update_fields)

    def mark_failed(self, error: str):
        """Mark the run as failed with an error message."""
        self.status = self.Status.FAILED
        self.error_message = error
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at"])

    def update_progress(self, step: "AiVisibilityRun.ProgressStep"):
        """Update the progress step."""
        self.progress_step = step
        self.save(update_fields=["progress_step"])
