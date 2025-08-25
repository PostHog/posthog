from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class SingleSessionSummary(ModelActivityMixin, UUIDModel):
    """
    Stores LLM-generated session summaries for caching and searching.
    Each summary represents analysis of a single session replay.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    session_id = models.CharField(max_length=200, help_text="Session replay ID")
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who requested the summary",
    )

    # Summary content
    summary = models.JSONField(help_text="Session summary in JSON format (SessionSummarySerializer schema)")

    # Searchable exception events
    exception_event_ids = ArrayField(
        models.CharField(max_length=200),
        default=list,
        blank=True,
        size=100,  # Maximum 100 exception event IDs
        help_text="List of event IDs where exceptions occurred for searchability",
    )

    # Context and metadata
    extra_summary_context = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional context passed to the summary (ExtraSummaryContext schema)",
    )
    run_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Summary run metadata (SessionSummaryRunMeta schema)",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    # TODO: Implement background job to delete summaries older than 1 year

    class Meta:
        db_table = "ee_single_session_summary"
        indexes = [
            models.Index(fields=["session_id"]),
            models.Index(fields=["team", "session_id"]),
            GinIndex(
                name="idx_exception_event_ids_gin",
                fields=["exception_event_ids"],
            ),
        ]

    def __str__(self):
        if self.extra_summary_context:
            return f"Summary for session {self.session_id} with extra context {self.extra_summary_context}"
        return f"Summary for session {self.session_id}"
