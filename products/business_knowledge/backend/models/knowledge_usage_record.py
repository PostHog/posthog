from django.db import models

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import UUIDModel


class KnowledgeUsageKey(models.TextChoices):
    """Billable meters. They must match the `usage_key` values in the billing service's plans config."""

    CHUNKS = "business_knowledge_chunks", "Chunks ingested"
    QUERIES = "business_knowledge_queries", "Queries"


class KnowledgeUsageRecord(UUIDModel):
    """Append-only record of one unit of billable business knowledge work.

    Ingestion writes one row per chunk write, in the same transaction as the chunks, so a rolled-back
    write records nothing. Retrieval writes one row per search. Rows are never updated, and deleting the
    source, document or chunks they describe leaves them in place, so a delete never removes usage.

    Nothing reads this table for billing yet. It meters usage so the pricing can be checked against real
    data before the usage report and the billing service start counting it.
    """

    # Canonical team, no FK: deleting a team must not cascade into usage history.
    team_id = models.BigIntegerField()
    usage_key = models.CharField(max_length=64, choices=KnowledgeUsageKey.choices)
    quantity = models.PositiveIntegerField()
    surface = models.CharField(max_length=32, blank=True, default="")
    # The search's trace id, so a retried Temporal activity is counted once.
    idempotency_key = models.CharField(max_length=128, null=True, blank=True)
    # Plain ids, kept to answer "why was I billed for this?" after a delete.
    source_id = models.UUIDField(null=True, blank=True)
    document_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TeamScopedManager()

    class Meta:
        db_table = "posthog_business_knowledge_knowledgeusagerecord"
        constraints = [
            models.UniqueConstraint(
                fields=["usage_key", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="bk_usage_idempotency_key",
            ),
        ]
        indexes = [
            models.Index(fields=["created_at", "team_id"], name="bk_usage_created_team"),
            models.Index(fields=["team_id", "usage_key", "created_at"], name="bk_usage_team_key_created"),
        ]

    def __str__(self) -> str:
        return f"{self.usage_key} x{self.quantity} (team {self.team_id})"
