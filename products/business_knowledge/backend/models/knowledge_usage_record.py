from django.db import models

from posthog.models.utils import UUIDModel


class KnowledgeUsageKey(models.TextChoices):
    """Billing usage keys. They must match the `usage_key` values in the billing service's plans config."""

    CHUNKS = "business_knowledge_chunks", "Chunks ingested"
    QUERIES = "business_knowledge_queries", "Queries"


class KnowledgeUsageRecord(UUIDModel):
    """Immutable billing receipt for one unit of billable business knowledge work.

    Ingestion writes one row per chunk write, in the same transaction as the chunks, so a rolled-back
    write bills nothing. Retrieval writes one row per search. Rows are never updated or deleted when the
    source, document or chunks they describe are deleted, so a delete never refunds usage.

    The nightly usage report and the in-product usage meter both read this table, so they always agree.
    """

    # The canonical team the knowledge is stored under (plain id, no FK), so child environments bill to
    # their parent and deleting a team never cascades into billing history.
    team_id = models.BigIntegerField()
    usage_key = models.CharField(max_length=64, choices=KnowledgeUsageKey.choices)
    quantity = models.PositiveIntegerField()
    # Where the work came from: a retrieval surface ("api", "support", ...) or an ingestion path.
    surface = models.CharField(max_length=32, blank=True, default="")
    # Set for retrieval: the search's trace id. A retried Temporal activity reuses its trace id, so the
    # unique constraint drops the duplicate instead of billing the same search twice.
    idempotency_key = models.CharField(max_length=128, null=True, blank=True)
    # Kept for support questions ("why was I billed for this?"). Plain ids so deletes never cascade.
    source_id = models.UUIDField(null=True, blank=True)
    document_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
            # Drives the daily per-team billing usage report, which buckets rows by write time.
            models.Index(fields=["created_at", "team_id"], name="bk_usage_created_team"),
            # Drives the in-product usage meter for one team over the current billing period.
            models.Index(fields=["team_id", "usage_key", "created_at"], name="bk_usage_team_key_created"),
        ]

    def __str__(self) -> str:
        return f"{self.usage_key} x{self.quantity} (team {self.team_id})"
