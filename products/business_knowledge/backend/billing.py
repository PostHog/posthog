"""Meters business knowledge usage into the append-only `KnowledgeUsageRecord` ledger.

Two meters, matching the pricing RFC:

- `business_knowledge_chunks`: every chunk written, on any ingest path. A refresh that re-indexes changed
  content writes its chunks again, so it counts again. Content a refresh finds unchanged is not
  re-chunked, so it is not counted. Sources PostHog generates by learning from support tickets count
  the same way.
- `business_knowledge_queries`: every knowledge search made with a `RetrievalTrace`, on any customer
  surface. PostHog's internal docs-shadow comparison is not metered.

The nightly usage report reads these totals (`usage_by_team`) and sends them to the billing service, which
does not charge for them until it has Business Knowledge products. No quota is enforced yet, so a metering
failure is logged and never fails the ingest or search that triggered it.
"""

from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Sum

import structlog

from .facade.contracts import KnowledgeUsageByTeam
from .models import KnowledgeUsageKey, KnowledgeUsageRecord

logger = structlog.get_logger(__name__)

# PostHog's internal docs-search comparison; the customer never sees its results.
UNMETERED_SURFACES = frozenset({"docs_shadow"})


def record_chunks_ingested(
    *,
    team_id: int,
    quantity: int,
    surface: str,
    source_id: UUID | None,
    document_id: UUID | None,
) -> None:
    """Record `quantity` chunks just written for `team_id`.

    Call inside the transaction that wrote the chunks, so a rollback removes the record with them.
    `team_id` must be the canonical team the chunks are stored under.
    """
    if quantity <= 0:
        return
    try:
        # Savepoint, so a failed insert can't poison the caller's transaction and roll back the chunks.
        with transaction.atomic():
            KnowledgeUsageRecord.objects.unscoped().create(
                team_id=team_id,
                usage_key=KnowledgeUsageKey.CHUNKS,
                quantity=quantity,
                surface=surface,
                source_id=source_id,
                document_id=document_id,
            )
    except Exception:
        logger.exception(
            "business_knowledge.usage_record_failed", usage_key=KnowledgeUsageKey.CHUNKS.value, team_id=team_id
        )


def record_query(*, team_id: int, trace_id: str, surface: str) -> None:
    """Record one knowledge search for `team_id`.

    The trace id is the idempotency key: a retried Temporal activity that reuses its trace id writes no
    second row. `team_id` must be the canonical team. Searches from `UNMETERED_SURFACES` write nothing.
    """
    if surface in UNMETERED_SURFACES:
        return
    try:
        with transaction.atomic():
            KnowledgeUsageRecord.objects.unscoped().get_or_create(
                usage_key=KnowledgeUsageKey.QUERIES,
                idempotency_key=trace_id,
                defaults={"team_id": team_id, "quantity": 1, "surface": surface},
            )
    except Exception:
        logger.exception(
            "business_knowledge.usage_record_failed", usage_key=KnowledgeUsageKey.QUERIES.value, team_id=team_id
        )


def usage_by_team(begin: datetime, end: datetime) -> KnowledgeUsageByTeam:
    """(team_id, total) rows for each meter, from rows written in [begin, end).

    Buckets by write time, so a row written late lands in the next report instead of being missed.
    """
    rows = (
        KnowledgeUsageRecord.objects.unscoped()
        .filter(created_at__gte=begin, created_at__lt=end)
        .values("team_id", "usage_key")
        .annotate(total=Sum("quantity"))
        .order_by("team_id", "usage_key")
    )
    totals: dict[KnowledgeUsageKey, list[tuple[int, int]]] = {key: [] for key in KnowledgeUsageKey}
    for row in rows:
        totals[KnowledgeUsageKey(row["usage_key"])].append((row["team_id"], row["total"]))
    return KnowledgeUsageByTeam(chunks=totals[KnowledgeUsageKey.CHUNKS], queries=totals[KnowledgeUsageKey.QUERIES])
