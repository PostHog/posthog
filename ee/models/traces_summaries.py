from django.db import models

from posthog.models.team.team import Team
from posthog.models.utils import UUIDTModel


class TraceSummary(UUIDTModel):
    class Meta:
        indexes = [
            models.Index(fields=["team", "trace_id"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team", "trace_id", "trace_summary_type"], name="unique_trace_summary"),
        ]

    class TraceSummaryType(models.TextChoices):
        """
        Traces could be summarized with different types of prompts for different use cases.
        """

        ISSUES_SEARCH = "issues_search"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    trace_summary_type = models.CharField(
        max_length=100, choices=TraceSummaryType.choices, default=TraceSummaryType.ISSUES_SEARCH
    )
    trace_id = models.CharField(max_length=255, help_text="Trace ID")
    summary = models.CharField(max_length=1000, help_text="Trace summary")
