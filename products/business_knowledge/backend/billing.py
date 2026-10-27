"""Bills business knowledge from the immutable `KnowledgeUsageRecord` ledger.

Two meters, matching the billing service's plans config:

- `business_knowledge_chunks`: every chunk written, on any ingest path. A refresh that re-indexes changed
  content writes its chunks again, so it bills again. Content a refresh finds unchanged is not re-chunked,
  so it is not billed. Sources PostHog generates by learning from support tickets bill the same way.
- `business_knowledge_queries`: every knowledge search, on any surface.

The ledger is the billing source of truth: the nightly usage report and the in-product usage meter both
read it. Each row is also mirrored to the `usage-ingestion` service so the usage counters can move to its
real-time mode later without touching these producers.
"""

import os
from datetime import UTC, datetime
from functools import partial
from queue import Full, Queue
from threading import Lock, Thread
from typing import cast
from uuid import UUID

from django.db import transaction
from django.db.models import IntegerField, Sum
from django.db.models.functions import Coalesce

import structlog

from posthog.dataclasses import frozen
from posthog.models.organization import Organization
from posthog.usage_ingestion.client import UsageRecord, report_usage

from .models import KnowledgeUsageKey, KnowledgeUsageRecord

logger = structlog.get_logger(__name__)

# Monthly free tiers. They mirror the free plans in the billing service's plans config, which is the
# source of truth; these only label the in-product usage meter.
FREE_CHUNKS_PER_MONTH = 15_000
FREE_QUERIES_PER_MONTH = 1_000

PRODUCER_ID = "business-knowledge"
_REPORT_SITE = "business_knowledge"
_UNITS = {
    KnowledgeUsageKey.CHUNKS: "chunks",
    KnowledgeUsageKey.QUERIES: "queries",
}


@frozen
class KnowledgeUsage:
    chunks: int
    queries: int


# The mirror is a blocking gRPC call with retries, so daemon workers send it off the request path:
# searches and ingestion never wait for it, and a slow gateway never holds up a worker's shutdown.
# Records still queued at exit, or dropped when the queue is full, are lost from the mirror only; the
# committed ledger row is what billing reads.
_MIRROR_WORKERS = 2
_mirror_queue: Queue[UsageRecord] = Queue(maxsize=1_000)
_mirror_lock = Lock()
_mirror_pid: int | None = None


def _send(record: UsageRecord) -> None:
    report_usage([record], site=_REPORT_SITE)


def _mirror_worker() -> None:
    while True:
        record = _mirror_queue.get()
        try:
            _send(record)
        except Exception:
            # One failed send must not end the worker.
            logger.warning("business_knowledge.usage_mirror_failed", usage_key=record.usage_key, exc_info=True)
        finally:
            _mirror_queue.task_done()


def _start_mirror_workers() -> None:
    # Threads do not survive a fork, so each process starts its own on first use.
    global _mirror_pid
    if _mirror_pid == os.getpid():
        return
    with _mirror_lock:
        if _mirror_pid == os.getpid():
            return
        for index in range(_MIRROR_WORKERS):
            Thread(target=_mirror_worker, name=f"bk-usage-mirror-{index}", daemon=True).start()
        _mirror_pid = os.getpid()


def _enqueue(record: UsageRecord) -> None:
    _start_mirror_workers()
    try:
        _mirror_queue.put_nowait(record)
    except Full:
        logger.warning("business_knowledge.usage_mirror_backlog_full", usage_key=record.usage_key)


def _mirror(record_id: str, team_id: int, usage_key: KnowledgeUsageKey, quantity: int) -> None:
    # Built now so the record's timestamp is the commit time, not the time a worker gets to it.
    _enqueue(
        UsageRecord(
            record_id=record_id,
            producer_id=PRODUCER_ID,
            team_id=team_id,
            usage_key=usage_key.value,
            unit=_UNITS[usage_key],
            quantity=quantity,
        )
    )


def _mirror_on_commit(record_id: str, team_id: int, usage_key: KnowledgeUsageKey, quantity: int) -> None:
    transaction.on_commit(partial(_mirror, record_id, team_id, usage_key, quantity))


def record_chunks_ingested(
    *,
    team_id: int,
    quantity: int,
    surface: str,
    source_id: UUID | None,
    document_id: UUID | None,
) -> None:
    """Bill `quantity` chunks just written for `team_id`.

    Call inside the transaction that wrote the chunks: a rollback then removes the bill with them.
    `team_id` must be the canonical team the chunks are stored under.
    """
    if quantity <= 0:
        return
    row = KnowledgeUsageRecord.objects.unscoped().create(
        team_id=team_id,
        usage_key=KnowledgeUsageKey.CHUNKS,
        quantity=quantity,
        surface=surface,
        source_id=source_id,
        document_id=document_id,
    )
    # The ledger row id is unique per write, so a refresh of the same document is a new billable record.
    _mirror_on_commit(str(row.id), team_id, KnowledgeUsageKey.CHUNKS, quantity)


def record_query(*, team_id: int, trace_id: str, surface: str) -> None:
    """Bill one knowledge search for `team_id`.

    The trace id is the idempotency key: a retried Temporal activity that reuses its trace id writes no
    second ledger row and sends nothing. Resending would bill twice in `usage-ingestion` when the retry
    lands on a later UTC day, because it only collapses duplicates within one day.
    """
    # Unscoped: the idempotency key is global, and the row's team is the canonical team passed in.
    _, created = KnowledgeUsageRecord.objects.unscoped().get_or_create(
        usage_key=KnowledgeUsageKey.QUERIES,
        idempotency_key=trace_id,
        defaults={"team_id": team_id, "quantity": 1, "surface": surface},
    )
    if created:
        _mirror_on_commit(trace_id, team_id, KnowledgeUsageKey.QUERIES, 1)


def _usage_by_team(
    usage_key: KnowledgeUsageKey,
    begin: datetime,
    end: datetime,
    # nosemgrep: tuple-return-prefer-dataclass -- (team_id, count) rows are the shared usage-report contract consumed by convert_team_usage_rows_to_dict.
) -> list[tuple[int, int]]:
    # Bucket by write time so a late row is never dropped from an already-run daily report.
    rows = (
        KnowledgeUsageRecord.objects.unscoped()
        .filter(created_at__gte=begin, created_at__lt=end, usage_key=usage_key)
        .values("team_id")
        .annotate(total=Coalesce(Sum("quantity"), 0, output_field=IntegerField()))
        .values_list("team_id", "total")
    )
    return cast(list[tuple[int, int]], list(rows))


def get_chunks_by_team(
    begin: datetime,
    end: datetime,
    # nosemgrep: tuple-return-prefer-dataclass -- (team_id, count) rows are the shared usage-report contract.
) -> list[tuple[int, int]]:
    return _usage_by_team(KnowledgeUsageKey.CHUNKS, begin, end)


def get_queries_by_team(
    begin: datetime,
    end: datetime,
    # nosemgrep: tuple-return-prefer-dataclass -- (team_id, count) rows are the shared usage-report contract.
) -> list[tuple[int, int]]:
    return _usage_by_team(KnowledgeUsageKey.QUERIES, begin, end)


@frozen
class UsagePeriod:
    start: datetime
    end: datetime


def current_usage_period(organization: Organization, now: datetime | None = None) -> UsagePeriod:
    """The organization's billing period when billing has synced one, else the calendar month."""
    now = now or datetime.now(UTC)
    billing_period = organization.current_billing_period
    if billing_period:
        start, end = (
            moment if moment.tzinfo else moment.replace(tzinfo=UTC)
            for moment in (billing_period.start, billing_period.end)
        )
        if start <= now < end:
            return UsagePeriod(start=start, end=end)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return UsagePeriod(start=start, end=end)


def get_team_usage(team_id: int, begin: datetime, end: datetime) -> KnowledgeUsage:
    """Usage for one canonical team in `[begin, end)`, for the in-product usage meter."""
    totals = dict(
        KnowledgeUsageRecord.objects.for_team(team_id, canonical=True)
        .filter(created_at__gte=begin, created_at__lt=end)
        .values("usage_key")
        .annotate(total=Coalesce(Sum("quantity"), 0, output_field=IntegerField()))
        .values_list("usage_key", "total")
    )
    return KnowledgeUsage(
        chunks=totals.get(KnowledgeUsageKey.CHUNKS.value, 0),
        queries=totals.get(KnowledgeUsageKey.QUERIES.value, 0),
    )
