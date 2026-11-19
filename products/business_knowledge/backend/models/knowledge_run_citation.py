from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

RUN_ID_MAX_LENGTH = 128
PERSIST_AS_MAX_LENGTH = 16


class KnowledgeRunCitation(TeamScopedRootMixin, UUIDModel):
    """One knowledge chunk that one support investigation run cited.

    Usage counts runs, not tickets. A ticket that is investigated three times
    produces three sets of rows.
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        # Creating a real FK takes SHARE ROW EXCLUSIVE on posthog_team.
        db_constraint=False,
        # The unique constraint and both indexes already lead with team_id.
        db_index=False,
        related_name="+",
    )
    run_id = models.CharField(max_length=RUN_ID_MAX_LENGTH)
    ticket_id = models.UUIDField()
    # Plain UUIDs. A refresh deletes and recreates chunks, and a deleted source or
    # document must not take its usage history with it.
    chunk_id = models.UUIDField()
    document_id = models.UUIDField()
    source_id = models.UUIDField()
    # "reply" or "findings": what the run left on the ticket.
    persist_as = models.CharField(max_length=PERSIST_AS_MAX_LENGTH, blank=True, default="")
    confidence = models.FloatField(null=True, blank=True)
    # Not auto_now_add: a backfill writes the time the run happened.
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            # A retried activity records the same run again.
            models.UniqueConstraint(fields=["team", "run_id", "chunk_id"], name="bk_run_citation_unique"),
        ]
        indexes = [
            models.Index(fields=["team", "source_id", "created_at"], name="bk_run_citation_team_source"),
            models.Index(fields=["team", "ticket_id"], name="bk_run_citation_team_ticket"),
        ]

    def __str__(self) -> str:
        return f"run {self.run_id} cited chunk {self.chunk_id}"
