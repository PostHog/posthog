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
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from .. import logic, safety
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

        return {
            "tombstoned_deleted": swept,
            "sources_due": len(due),
            "sources_refreshed": refreshed,
            "sources_skipped": skipped,
            "sources_failed": failed,
            "documents_classified": classified.get("classified", 0),
            "documents_unsafe": classified.get("unsafe", 0),
        }

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        # The coordinator takes no inputs; tolerate any payload from manual triggers.
        _ = json.loads(inputs[0]) if inputs else None
        return None
