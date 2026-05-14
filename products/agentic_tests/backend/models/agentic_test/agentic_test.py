"""AgenticTest model."""

from django.db import models

from posthog.models.utils import UUIDModel


class AgenticTest(UUIDModel):
    """
    A single agentic test: an LLM-generated natural-language prompt that an agent
    executes against `target_url`. Pass/fail comes from the agent's own evaluation
    of whether the prompt was satisfied.

    The `prompt` itself is owned by the generation step (a teammate's piece);
    this model is the storage and management surface around it.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        PROPOSED = "proposed", "Proposed"
        REJECTED = "rejected", "Rejected"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="agentic_tests")
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    target_url = models.URLField(max_length=2048)
    prompt = models.TextField(help_text="Natural-language instructions for the browser agent.")

    status = models.CharField(max_length=20, choices=Status, default=Status.PROPOSED)

    source_replay_id = models.CharField(max_length=255, null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    schedule_cron = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text=(
            "Cron expression (5 fields, UTC) describing the run cadence. Empty means manual-only — no automatic runs."
        ),
    )
    next_run_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the next scheduled run is due. Null when the test is not on a schedule.",
    )

    assertions = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of post-run checks the test must satisfy in addition to the agent's own "
            "self-evaluation. Each item: {type, ...config}. Supported types: url_contains, "
            "event_captured."
        ),
    )

    class Meta:
        db_table = "posthog_agentictest"
        indexes = [
            models.Index(fields=["team", "status"]),
        ]
