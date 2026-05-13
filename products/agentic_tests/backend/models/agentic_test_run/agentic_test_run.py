"""AgenticTestRun model."""

from django.db import models

from posthog.models.utils import UUIDModel


class AgenticTestRun(UUIDModel):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        TIMEOUT = "timeout", "Timeout"
        ERROR = "error", "Error"

    agentic_test = models.ForeignKey(
        "agentic_tests.AgenticTest",
        on_delete=models.CASCADE,
        related_name="runs",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status, default=Status.RUNNING)
    duration_ms = models.IntegerField(null=True, blank=True)

    output = models.JSONField(default=dict, blank=True, help_text="Raw response from the browser agent.")
    error_message = models.TextField(blank=True, default="")

    external_session_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Runner-specific session id (e.g. browserbase) so we can deep-link back to the agent run.",
    )
    screenshot_url = models.URLField(max_length=2048, blank=True, default="")

    class Meta:
        db_table = "posthog_agentictestrun"
        indexes = [
            models.Index(fields=["agentic_test", "-started_at"]),
        ]
