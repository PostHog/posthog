from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .constants import GapStatus
from .knowledge_source import KnowledgeSource


class KnowledgeGapSuggestion(TeamScopedRootMixin, UUIDModel):
    """A topic the support AI couldn't answer from the knowledge base.

    One row per (ticket, normalized topic). The ticket view filters by ticket_id;
    the BK view aggregates by normalized_topic across tickets.
    """

    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="business_knowledge_gap_suggestions"
    )
    ticket_id = models.UUIDField(db_index=True)
    # Rows are created by the support AI pipeline, not a user, so there's no `created_by` FK
    # (avoids an FK constraint on the hot posthog_user table). Just track when the gap appeared.
    created_at = models.DateTimeField(auto_now_add=True)
    topic = models.TextField()
    normalized_topic = models.CharField(max_length=255)
    ticket_type = models.CharField(max_length=32, blank=True, default="")
    outcome = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(max_length=16, choices=GapStatus.choices, default=GapStatus.PENDING)
    resolved_source = models.ForeignKey(
        KnowledgeSource, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "posthog_business_knowledge_knowledgegapsuggestion"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "ticket_id", "normalized_topic"],
                name="bk_gap_unique_per_ticket_topic",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "status", "normalized_topic"], name="bk_gap_team_status_topic"),
        ]

    def __str__(self) -> str:
        return f"Gap: {self.topic[:60]} (ticket={self.ticket_id})"
