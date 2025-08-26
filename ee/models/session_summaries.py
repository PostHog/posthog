from dataclasses import asdict, dataclass
from typing import Any, Optional

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDModel


@dataclass(frozen=True)
class ExtraSummaryContext:
    focus_area: str | None = None


@dataclass(frozen=True)
class SessionSummaryRunMeta:
    """Metadata about the run of the summary generation"""

    model_used: str
    visual_confirmation: bool


@dataclass(frozen=True)
class SessionSummaryPage:
    """Paginated results for session summaries"""

    limit: int
    has_next: bool
    results: list["SingleSessionSummary"]


class SingleSessionSummaryManager(models.Manager):
    """Manager for SingleSessionSummary with utility methods."""

    def get_summary(
        self, team_id: int, session_id: str, extra_summary_context: ExtraSummaryContext | None = None
    ) -> Optional["SingleSessionSummary"]:
        """Get a session summary if it exists"""
        queryset = self.filter(team_id=team_id, session_id=session_id)
        # Filter by context presence
        if extra_summary_context is not None:
            # Should have context
            queryset = queryset.filter(extra_summary_context__isnull=False)
        else:
            # No context to match
            queryset = queryset.filter(extra_summary_context__isnull=True)
        summary = queryset.order_by("-created_at").first()
        # No summary found
        if not summary:
            return None
        # Summary found, no context to match
        if extra_summary_context is None:
            return summary
        # Summary found, context to match
        if summary.extra_summary_context != asdict(extra_summary_context):
            return None
        return summary

    def add_summary(
        self,
        team_id: int,
        session_id: str,
        summary: dict[str, Any],
        exception_event_ids: list[str],
        extra_summary_context: ExtraSummaryContext | None = None,
        run_metadata: SessionSummaryRunMeta | None = None,
        created_by: Optional[User] = None,
    ) -> "SingleSessionSummary":
        """Store a new session summary"""
        extra_summary_context_dict = asdict(extra_summary_context) if extra_summary_context else None
        run_metadata_dict = asdict(run_metadata) if run_metadata else {}
        return self.create(
            team_id=team_id,
            session_id=session_id,
            summary=summary,
            # Enforce max 100 limit, just in case
            exception_event_ids=exception_event_ids[:100],
            extra_summary_context=extra_summary_context_dict,
            run_metadata=run_metadata_dict,
            created_by=created_by,
        )

    def get_bulk_summaries(
        self,
        team: Team,
        session_ids: list[str],
        extra_summary_context: ExtraSummaryContext | None = None,
        # Summaries could be up to 50kb in JSON, so playing it safe
        limit: int = 100,
        offset: int = 0,
    ) -> SessionSummaryPage:
        """Get multiple session summaries with pagination"""
        queryset = self.filter(team=team, session_id__in=session_ids)
        # Filter by context presence at DB level
        if extra_summary_context is not None:
            # Should have context
            queryset = queryset.filter(extra_summary_context__isnull=False)
        else:
            # No context to match
            queryset = queryset.filter(extra_summary_context__isnull=True)
        # Get the latest summary per session_id with limit+1 to check for more records
        queryset = queryset.order_by("session_id", "-created_at").distinct("session_id")
        # Use Django slicing to SQL LIMIT/OFFSET at the database level
        db_results = list(queryset[offset : offset + limit + 1])
        # Check if there are more records in the database
        has_next = len(db_results) > limit
        # Trim to actual limit
        db_results = db_results[:limit]
        # Filter by the context in Python to ensure the proper match
        if extra_summary_context is not None:
            extra_summary_context_dict = asdict(extra_summary_context)
            filtered_summaries = [s for s in db_results if s.extra_summary_context == extra_summary_context_dict]
        else:
            filtered_summaries = db_results
        return SessionSummaryPage(
            results=filtered_summaries,
            limit=limit,
            has_next=has_next,
        )


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

    objects = SingleSessionSummaryManager()

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
