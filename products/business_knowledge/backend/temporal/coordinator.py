"""
Background-refresh coordinator for business_knowledge.

One global hourly Temporal schedule drives this single coordinator workflow
(no per-source schedules — see the Stage 5 plan for why). Each run:

  1. sweeps tombstoned documents past their grace period,
  2. refreshes every URL source whose auto-refresh interval is due,
  3. classifies any documents still awaiting a safety verdict.

Refresh runs *before* classification so that documents whose content changed
during the refresh (reset to ``unknown``) get classified in the same pass —
otherwise they'd be searchable as ``unknown`` until the next hourly run.

Per-source refresh reuses the shipped, idempotent `logic.refresh_source`; the
existing per-team advisory lock ("one PROCESSING source per team") plus the
schedule's SKIP overlap policy prevent concurrent double-refresh, so there is
no bespoke concurrency cap here.
"""

import json
import asyncio
import dataclasses
from collections import defaultdict
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import emit_embedding_request
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from .. import logic, safety
from ..constants import BK_EMBEDDING_DOCUMENT_TYPE, BK_EMBEDDING_MODEL, BK_EMBEDDING_PRODUCT, BK_EMBEDDING_RENDERING
from ..models import SafetyVerdict

logger = structlog.get_logger(__name__)

# How many source refreshes to run concurrently within one coordinator pass.
# Bounded so a large backlog can't flood the shared worker queue.
MAX_CONCURRENT_REFRESHES = 25


@dataclasses.dataclass(frozen=True)
class RefreshSourceInputs:
    team_id: int
    source_id: str


@dataclasses.dataclass(frozen=True)
class IngestSourceInputs:
    team_id: int
    source_id: str


@activity.defn
async def sweep_tombstoned_documents_activity() -> int:
    """Hard-delete documents tombstoned past the 7-day grace period."""
    return await database_sync_to_async(logic.sweep_tombstoned_documents, thread_sensitive=False)()


@activity.defn
async def classify_pending_documents_activity() -> dict[str, Any]:
    """Classify documents whose safety verdict is still unknown."""
    docs = await database_sync_to_async(logic.list_documents_pending_classification, thread_sensitive=False)()
    if not docs:
        return {"classified": 0, "unsafe": 0}
    async with Heartbeater():
        results = await safety.classify_documents(docs)
        for result in results:
            await database_sync_to_async(logic.set_document_safety, thread_sensitive=False)(
                team_id=result.team_id,
                document_id=result.document_id,
                verdict=result.verdict,
                reason=result.reason,
                content_hash=result.content_hash,
            )
    unsafe = sum(1 for r in results if r.verdict == SafetyVerdict.UNSAFE)
    return {"classified": len(results), "unsafe": unsafe}


def _produce_document_chunks(doc: logic.DocumentToEmbed) -> None:
    """Produce every chunk of one doc to the embedding pipeline (sync Kafka
    produce). ``doc.timestamp`` is the embedding row timestamp — the stable
    ``created_at`` for young first emissions, ``now()`` for old first emissions
    (docs whose ``created_at`` is past the TTL refresh window), or ``now()``
    for TTL refreshes."""
    for chunk in doc.chunks:
        emit_embedding_request(
            content=chunk.content,
            team_id=doc.team_id,
            product=BK_EMBEDDING_PRODUCT,
            document_type=BK_EMBEDDING_DOCUMENT_TYPE,
            rendering=BK_EMBEDDING_RENDERING,
            document_id=str(chunk.chunk_id),
            models=[BK_EMBEDDING_MODEL],
            timestamp=doc.timestamp,
            # `document_id` lets the read path group a doc's chunk vectors and
            # re-join to Postgres; the chunk's own id is the embedding row's id.
            metadata={"document_id": str(doc.document_id)},
        )


def _emit_one_document(doc: logic.DocumentToEmbed) -> int:
    """
    Produce every chunk of one SAFE doc to the embedding pipeline, then stamp
    the doc as emitted. Runs in a worker thread (sync Kafka produce + DB write).

    If any chunk produce raises, the exception propagates BEFORE the stamp, so
    the doc stays unstamped and the next pass retries the whole doc. Re-emitting
    chunks that already landed is harmless — the shared table dedupes on
    (chunk_id, timestamp) via ReplacingMergeTree.
    """
    _produce_document_chunks(doc)
    logic.mark_document_embeddings_emitted(team_id=doc.team_id, document_id=doc.document_id)
    return len(doc.chunks)


def _reemit_one_document(doc: logic.DocumentToEmbed) -> int:
    """
    Re-produce every chunk of an aging SAFE doc with a FRESH timestamp, then
    re-stamp ``embeddings_emitted_at``. Used by the TTL-refresh pass to keep
    vectors alive past the 3-month ClickHouse TTL.

    ``doc.timestamp`` is ``now()`` here (set by
    ``logic.list_documents_for_embedding_refresh``) so the re-emit lands a fresh
    row that resets the TTL clock; the prior row ages out under its own TTL. As
    with first emission, a produce error propagates before the re-stamp, so the
    doc keeps its old stamp and is retried on a later pass.
    """
    _produce_document_chunks(doc)
    logic.restamp_document_embeddings_emitted(team_id=doc.team_id, document_id=doc.document_id)
    return len(doc.chunks)


@activity.defn
async def emit_pending_embeddings_activity() -> dict[str, Any]:
    """
    Produce embeddings for SAFE documents that haven't been embedded yet.

    Bounded by ``PENDING_EMBEDDING_SCAN_CAP``; the hourly coordinator drains the
    backlog (and the initial cross-team backfill) over many passes. Per-doc
    failures are logged and skipped without stamping, so they retry next pass.
    """
    docs = await database_sync_to_async(logic.list_documents_pending_embedding, thread_sensitive=False)()
    documents_embedded = 0
    chunks_emitted = 0
    for doc in docs:
        try:
            written = await database_sync_to_async(_emit_one_document, thread_sensitive=False)(doc)
        except Exception:
            logger.exception(
                "business_knowledge.embedding.emit_failed",
                team_id=doc.team_id,
                document_id=str(doc.document_id),
            )
            continue
        documents_embedded += 1
        chunks_emitted += written
    return {"documents_embedded": documents_embedded, "chunks_emitted": chunks_emitted}


@activity.defn
async def refresh_aging_embeddings_activity() -> dict[str, Any]:
    """
    Re-emit chunk embeddings for SAFE docs whose vectors are aging toward the
    3-month ClickHouse TTL, so long-lived knowledge never silently loses its
    vectors and falls back to FTS-only.

    Bounded by ``REEMIT_EMBEDDING_SCAN_CAP`` (oldest-emitted docs first); a large
    refresh wave drains over many hourly passes. The re-emit uses a fresh
    timestamp=now() (the TTL is on the embedding row timestamp, so the stable
    created_at would not reset it) and re-stamps ``embeddings_emitted_at`` so the
    doc drops out of the refresh window for another cycle. Per-doc failures are
    logged and skipped without re-stamping, so they retry on a later pass.
    """
    docs = await database_sync_to_async(logic.list_documents_for_embedding_refresh, thread_sensitive=False)()
    documents_refreshed = 0
    chunks_reemitted = 0
    for doc in docs:
        try:
            written = await database_sync_to_async(_reemit_one_document, thread_sensitive=False)(doc)
        except Exception:
            logger.exception(
                "business_knowledge.embedding.refresh_failed",
                team_id=doc.team_id,
                document_id=str(doc.document_id),
            )
            continue
        documents_refreshed += 1
        chunks_reemitted += written
    return {"documents_refreshed": documents_refreshed, "chunks_reemitted": chunks_reemitted}


def _present_chunk_ids_in_clickhouse(team_id: int, chunk_ids: list[UUID]) -> set[str]:
    """Return the subset of ``chunk_ids`` that already have a vector row in the
    shared ClickHouse embeddings table for this team + model. HogQL auto-scopes
    to the team, so no manual team_id filter is needed."""
    if not chunk_ids:
        return set()
    team = Team.objects.get(pk=team_id)
    query = """
        SELECT DISTINCT document_id
        FROM document_embeddings
        WHERE product = {product}
          AND document_type = {document_type}
          AND model_name = {model_name}
          AND document_id IN {chunk_ids}
    """
    result = execute_hogql_query(
        query=query,
        team=team,
        placeholders={
            "product": ast.Constant(value=BK_EMBEDDING_PRODUCT),
            "document_type": ast.Constant(value=BK_EMBEDDING_DOCUMENT_TYPE),
            "model_name": ast.Constant(value=BK_EMBEDDING_MODEL),
            "chunk_ids": ast.Constant(value=[str(c) for c in chunk_ids]),
        },
    )
    return {row[0] for row in (result.results or [])}


@activity.defn
async def reconcile_embeddings_activity() -> dict[str, Any]:
    """
    Re-verify that already-emitted SAFE docs actually landed in ClickHouse.

    ``embeddings_emitted_at`` only means "produced to Kafka". If a produce was
    lost or the worker dropped it, the doc would silently serve FTS-only forever.
    This bounded pass re-checks the oldest-emitted docs and, when NONE of a doc's
    chunk vectors are present, clears the stamp so the pending pass re-emits.

    Conservative on purpose: we only re-null when zero vectors are present (a
    clear "never landed" signal). Partial loss is left for a follow-up so a
    chunk the worker legitimately skips can't drive an endless re-emit loop.
    """
    docs = await database_sync_to_async(logic.list_documents_for_embedding_reconciliation, thread_sensitive=False)()

    # One ClickHouse query per team, not per doc: HogQL auto-scopes to a single
    # team so we can't batch across teams, but within a team we union every doc's
    # chunk_ids into one IN-list and compare the returned present-set in Python.
    docs_by_team: dict[int, list[logic.EmittedDocument]] = defaultdict(list)
    for doc in docs:
        docs_by_team[doc.team_id].append(doc)

    re_nulled = 0
    for team_id, team_docs in docs_by_team.items():
        chunk_ids = [chunk_id for doc in team_docs for chunk_id in doc.chunk_ids]
        present = await database_sync_to_async(_present_chunk_ids_in_clickhouse, thread_sensitive=False)(
            team_id, chunk_ids
        )
        for doc in team_docs:
            # Conservative: only re-null when NONE of the doc's chunks landed.
            if any(str(chunk_id) in present for chunk_id in doc.chunk_ids):
                continue
            await database_sync_to_async(logic.clear_document_embeddings_emitted, thread_sensitive=False)(
                team_id=team_id, document_id=doc.document_id
            )
            re_nulled += 1
    return {"reconciled": len(docs), "re_nulled": re_nulled}


@activity.defn
async def list_due_refresh_sources_activity() -> list[tuple[int, str, str]]:
    """Return (team_id, source_id, host) for URL sources whose refresh is due."""
    due = await database_sync_to_async(logic.list_due_refresh_sources, thread_sensitive=False)()
    return [(team_id, str(source_id), host) for team_id, source_id, host in due]


def _host_serialized_batches(
    due: list[tuple[int, str, str]],
    max_concurrent: int,
) -> list[list[RefreshSourceInputs]]:
    """
    Split due sources into sequential batches where no host repeats within a
    batch. Batches run one after another, so two sources on the same host never
    refresh concurrently — bounding load on any single origin to one refresh at
    a time regardless of how many teams point at it.
    """
    by_host: dict[str, list[RefreshSourceInputs]] = {}
    for team_id, source_id, host in due:
        by_host.setdefault(host, []).append(RefreshSourceInputs(team_id=team_id, source_id=source_id))

    batches: list[list[RefreshSourceInputs]] = []
    while by_host:
        batch: list[RefreshSourceInputs] = []
        for host in list(by_host.keys()):
            if len(batch) >= max_concurrent:
                break
            batch.append(by_host[host].pop(0))
            if not by_host[host]:
                del by_host[host]
        batches.append(batch)
    return batches


@activity.defn
async def refresh_knowledge_source_activity(inputs: RefreshSourceInputs) -> dict[str, Any]:
    """
    Refresh one URL source by reusing the synchronous `logic.refresh_source`.

    Expected outcomes (busy, unreachable, quota) are recorded on the row by
    `refresh_source` itself and returned as a status here — never raised — so
    Temporal doesn't retry them. Unexpected exceptions propagate for retry.
    """
    log = logger.bind(team_id=inputs.team_id, source_id=inputs.source_id)
    try:
        await database_sync_to_async(logic.refresh_source, thread_sensitive=False)(
            source_id=UUID(inputs.source_id), team_id=inputs.team_id
        )
    except logic.SourceBusyError:
        return {"status": "skipped", "reason": "busy"}
    except (logic.InvalidUrlError, logic.UrlFetchFailedError, logic.EmptyContentError, logic.QuotaExceededError) as exc:
        log.info("business_knowledge.refresh.recorded_failure", error_type=type(exc).__name__)
        return {"status": "error", "reason": type(exc).__name__}
    return {"status": "ok"}


@activity.defn
async def execute_refresh_knowledge_source_activity(inputs: RefreshSourceInputs) -> dict[str, Any]:
    """
    Execute the fetch+rebuild half of a refresh for a source already claimed
    PROCESSING. Used by the ad-hoc refresh workflow (user clicks "Re-fetch").
    """
    log = logger.bind(team_id=inputs.team_id, source_id=inputs.source_id)
    try:
        await database_sync_to_async(logic.execute_refresh_source, thread_sensitive=False)(
            source_id=UUID(inputs.source_id), team_id=inputs.team_id
        )
    except (logic.InvalidUrlError, logic.UrlFetchFailedError, logic.EmptyContentError, logic.QuotaExceededError) as exc:
        log.info("business_knowledge.refresh.recorded_failure", error_type=type(exc).__name__)
        return {"status": "error", "reason": type(exc).__name__}
    return {"status": "ok"}


@activity.defn
async def ingest_knowledge_source_activity(inputs: IngestSourceInputs) -> dict[str, Any]:
    """
    Fetch + index a freshly-created PROCESSING source in the background.

    Reuses the synchronous `logic.ingest_source`. Expected ingestion failures
    (unreachable URL, empty content, quota) are recorded on the row by the
    ingest path and reported as a status here — never raised — so Temporal
    doesn't retry them. Unexpected exceptions propagate for retry.
    """
    log = logger.bind(team_id=inputs.team_id, source_id=inputs.source_id)
    try:
        await database_sync_to_async(logic.ingest_source, thread_sensitive=False)(
            source_id=UUID(inputs.source_id), team_id=inputs.team_id
        )
    except (logic.InvalidUrlError, logic.UrlFetchFailedError, logic.EmptyContentError, logic.QuotaExceededError) as exc:
        log.info("business_knowledge.ingest.recorded_failure", error_type=type(exc).__name__)
        return {"status": "error", "reason": type(exc).__name__}
    return {"status": "ok"}


@workflow.defn(name="business-knowledge-ingest-source")
class BusinessKnowledgeIngestSourceWorkflow(PostHogWorkflow):
    @workflow.run
    async def run(self, inputs: IngestSourceInputs) -> dict[str, Any]:
        return await workflow.execute_activity(
            ingest_knowledge_source_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

    @staticmethod
    def parse_inputs(inputs: list[str]) -> IngestSourceInputs:
        loaded = json.loads(inputs[0])
        return IngestSourceInputs(**loaded)


@workflow.defn(name="business-knowledge-refresh-source")
class BusinessKnowledgeRefreshSourceWorkflow(PostHogWorkflow):
    """One-shot workflow for ad-hoc manual refreshes (user clicks "Re-fetch")."""

    @workflow.run
    async def run(self, inputs: RefreshSourceInputs) -> dict[str, Any]:
        return await workflow.execute_activity(
            execute_refresh_knowledge_source_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RefreshSourceInputs:
        loaded = json.loads(inputs[0])
        return RefreshSourceInputs(**loaded)


@workflow.defn(name="business-knowledge-refresh-coordinator")
class BusinessKnowledgeRefreshCoordinatorWorkflow(PostHogWorkflow):
    @workflow.run
    async def run(self) -> dict[str, Any]:
        swept = await workflow.execute_activity(
            sweep_tombstoned_documents_activity,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Refresh *before* classify: refreshed docs whose content changed are
        # reset to `unknown`, so running classification second picks them up in
        # the same pass instead of leaving them searchable until the next run.
        due: list[tuple[int, str, str]] = await workflow.execute_activity(
            list_due_refresh_sources_activity,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        refreshed = skipped = failed = 0
        for batch in _host_serialized_batches(due, MAX_CONCURRENT_REFRESHES):
            results = await asyncio.gather(
                *(
                    workflow.execute_activity(
                        refresh_knowledge_source_activity,
                        inputs,
                        start_to_close_timeout=timedelta(minutes=10),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                    for inputs in batch
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    failed += 1
                elif result.get("status") == "ok":
                    refreshed += 1
                else:
                    skipped += 1

        classified = await workflow.execute_activity(
            classify_pending_documents_activity,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # Reconcile first so any "emitted but never landed in ClickHouse" docs are
        # un-stamped, then the emit pass re-produces them alongside the newly-SAFE
        # docs classified just above — all in this one pass.
        reconciled = await workflow.execute_activity(
            reconcile_embeddings_activity,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        embedded = await workflow.execute_activity(
            emit_pending_embeddings_activity,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # Keep long-lived vectors alive past the 3-month CH TTL by re-emitting
        # aging SAFE docs. Runs last (lowest urgency) and re-stamps with now()
        # so a refreshed doc won't be touched again for a full window.
        ttl_refreshed = await workflow.execute_activity(
            refresh_aging_embeddings_activity,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        return {
            "tombstoned_deleted": swept,
            "sources_due": len(due),
            "sources_refreshed": refreshed,
            "sources_skipped": skipped,
            "sources_failed": failed,
            "documents_classified": classified.get("classified", 0),
            "documents_unsafe": classified.get("unsafe", 0),
            "embeddings_reconciled": reconciled.get("reconciled", 0),
            "embeddings_re_nulled": reconciled.get("re_nulled", 0),
            "documents_embedded": embedded.get("documents_embedded", 0),
            "chunks_emitted": embedded.get("chunks_emitted", 0),
            "embeddings_ttl_refreshed": ttl_refreshed.get("documents_refreshed", 0),
            "chunks_reemitted": ttl_refreshed.get("chunks_reemitted", 0),
        }

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        # The coordinator takes no inputs; tolerate any payload from manual triggers.
        _ = json.loads(inputs[0]) if inputs else None
        return None
