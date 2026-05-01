"""
Postgres-backed batch consumer for warehouse source loading.

Replaces KafkaConsumerService with a single asyncio process that polls the
batch queue, groups work by (team_id, schema_id), processes groups concurrently
(batches within a group run sequentially), and uses advisory locks for
cross-pod coordination.
"""

from __future__ import annotations

import time
import signal
import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import psycopg
import structlog
from asgiref.sync import sync_to_async

from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import BatchQueue, PendingBatch
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.metrics import (
    ACTIVE_GROUPS,
    BATCH_PROCESSING_DURATION_SECONDS,
    BATCH_RETRY_TOTAL,
    BATCHES_PROCESSED_TOTAL,
    POLL_BATCHES_FETCHED,
    POLL_DURATION_SECONDS,
    RECOVERY_SWEEPS_TOTAL,
    RUNS_FAILED_TOTAL,
)

from products.warehouse_sources_queue.backend.models import SourceBatchStatus

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS = 3
POLL_INTERVAL_SECONDS = 2.0


RECOVERY_INTERVAL_SECONDS = 30.0


@dataclass
class ConsumerConfig:
    """Tuning knobs for the batch consumer."""

    database_url: str
    max_concurrency: int = 16
    max_attempts: int = MAX_ATTEMPTS
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS
    poll_limit: int = 50
    health_port: int = 8080
    health_timeout_seconds: float = 60.0
    recovery_interval_seconds: float = RECOVERY_INTERVAL_SECONDS


class BatchConsumer:
    """
    Single-process consumer that polls Postgres for pending batches, groups them
    by (team_id, schema_id), and processes each group concurrently while batches
    within a group run sequentially. Advisory locks prevent two pods from
    working on the same (team_id, schema_id) simultaneously.
    """

    def __init__(
        self,
        config: ConsumerConfig,
        process_batch: ProcessBatchFn,
        health_reporter: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._process_batch = process_batch
        self._health_reporter = health_reporter
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self._shutdown = asyncio.Event()
        self._conn: psycopg.AsyncConnection[Any] | None = None
        self._recovery_conn: psycopg.AsyncConnection[Any] | None = None
        self._recovery_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        """Main loop: poll → group → process → unlock → repeat."""
        self._install_signal_handlers()

        self._conn = await psycopg.AsyncConnection.connect(
            self._config.database_url,
            autocommit=True,
        )
        self._recovery_conn = await psycopg.AsyncConnection.connect(
            self._config.database_url,
            autocommit=True,
        )

        logger.info(
            "batch_consumer_started",
            max_concurrency=self._config.max_concurrency,
            poll_interval=self._config.poll_interval_seconds,
            poll_limit=self._config.poll_limit,
        )

        try:
            await self._recovery_sweep()
            self._recovery_task = asyncio.create_task(self._recovery_loop())

            while not self._shutdown.is_set():
                if self._health_reporter:
                    self._health_reporter()

                poll_start = time.monotonic()
                batches = await BatchQueue.get_unprocessed_and_lock(
                    self._conn,
                    limit=self._config.poll_limit,
                )
                POLL_DURATION_SECONDS.observe(time.monotonic() - poll_start)
                POLL_BATCHES_FETCHED.observe(len(batches))

                if not batches:
                    try:
                        await asyncio.wait_for(
                            self._shutdown.wait(),
                            timeout=self._config.poll_interval_seconds,
                        )
                    except TimeoutError:
                        pass
                    continue

                groups = _group_by_key(batches)

                logger.debug(
                    "poll_returned",
                    batch_count=len(batches),
                    group_count=len(groups),
                )

                ACTIVE_GROUPS.inc(len(groups))
                try:
                    await asyncio.gather(
                        *[self._process_group(key, group_batches) for key, group_batches in groups.items()]
                    )
                finally:
                    ACTIVE_GROUPS.dec(len(groups))

        finally:
            await self._close()

    async def _process_group(
        self,
        key: tuple[int, str],
        batches: list[PendingBatch],
    ) -> None:
        """Process all batches for a (team_id, schema_id) sequentially, then unlock."""
        team_id, schema_id = key
        await self._semaphore.acquire()
        try:
            for batch in batches:
                if self._shutdown.is_set():
                    logger.info(
                        "shutdown_mid_group",
                        team_id=team_id,
                        schema_id=schema_id,
                        remaining=len(batches) - batches.index(batch),
                    )
                    break
                await self._process_single(batch)
        finally:
            self._semaphore.release()
            assert self._conn is not None
            await BatchQueue.unlock_for_batches(self._conn, batches=batches)

    async def _process_single(self, batch: PendingBatch) -> None:
        """Increment attempt, check max retries, then process the batch."""
        assert self._conn is not None

        team_id = str(batch.team_id)
        schema_id = batch.schema_id
        attempt = batch.latest_attempt + 1

        # Check before we even try — if already at max, fail the whole run.
        if attempt > self._config.max_attempts:
            logger.error(
                "batch_max_retries_exceeded",
                batch_id=batch.id,
                run_uuid=batch.run_uuid,
                attempt=attempt,
            )
            await self._fail_run(batch, reason=f"max retries exceeded (attempt {attempt})")
            return

        # Pre-increment: if we OOM here, recovery sees attempt=N+1
        # and knows this attempt was consumed.
        await BatchQueue.update_status(
            self._conn,
            batch_id=batch.id,
            job_state=SourceBatchStatus.State.EXECUTING,
            attempt=attempt,
        )

        try:
            start = time.monotonic()
            await self._process_batch(batch)
            BATCH_PROCESSING_DURATION_SECONDS.labels(team_id=team_id, schema_id=schema_id).observe(
                time.monotonic() - start
            )

            await BatchQueue.update_status(
                self._conn,
                batch_id=batch.id,
                job_state=SourceBatchStatus.State.SUCCEEDED,
                attempt=attempt,
            )
            BATCHES_PROCESSED_TOTAL.labels(team_id=team_id, schema_id=schema_id, status="success").inc()
        except Exception as e:
            BATCHES_PROCESSED_TOTAL.labels(team_id=team_id, schema_id=schema_id, status="error").inc()
            BATCH_RETRY_TOTAL.labels(attempt=str(attempt), error_type=type(e).__name__).inc()

            if attempt >= self._config.max_attempts:
                logger.exception(
                    "batch_failed_no_retries_left",
                    batch_id=batch.id,
                    run_uuid=batch.run_uuid,
                    attempt=attempt,
                )
                await self._fail_run(batch, reason=f"max retries exceeded: {e}")
            else:
                logger.warning(
                    "batch_failed_will_retry",
                    batch_id=batch.id,
                    attempt=attempt,
                    error=str(e),
                )
                await BatchQueue.update_status(
                    self._conn,
                    batch_id=batch.id,
                    job_state=SourceBatchStatus.State.WAITING_RETRY,
                    attempt=attempt,
                    error_response={"error": str(e)[:1000]},
                )

    async def _fail_run(
        self,
        batch: PendingBatch,
        reason: str,
        conn: psycopg.AsyncConnection[Any] | None = None,
    ) -> None:
        """Fail all pending batches in this run and mark the ExternalDataJob as failed."""
        conn = conn or self._conn
        assert conn is not None

        await BatchQueue.fail_run(conn, run_uuid=batch.run_uuid, reason=reason)
        RUNS_FAILED_TOTAL.inc()

        await sync_to_async(_update_job_status_to_failed)(
            job_id=batch.job_id,
            team_id=batch.team_id,
            error=reason,
        )

    async def _recovery_loop(self) -> None:
        """Run recovery sweeps periodically until shutdown."""
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self._config.recovery_interval_seconds,
                )
            except TimeoutError:
                pass

            if self._shutdown.is_set():
                break

            try:
                await self._recovery_sweep()
            except Exception:
                logger.exception("recovery_sweep_error")

    async def _recovery_sweep(self) -> None:
        """Recover batches left in 'executing' by a crashed pod."""
        conn = self._recovery_conn or self._conn
        assert conn is not None

        stale = await BatchQueue.get_stale_executing(conn)
        if not stale:
            RECOVERY_SWEEPS_TOTAL.labels(outcome="clean").inc()
            return

        RECOVERY_SWEEPS_TOTAL.labels(outcome="orphans_found").inc()
        logger.info("recovery_sweep_found_stale_batches", count=len(stale))

        for batch in stale:
            # latest_attempt was already incremented before the crash
            # (pre-increment in _process_single), so no +1 needed here.
            if batch.latest_attempt >= self._config.max_attempts:
                await self._fail_run(batch, reason="max retries exceeded (likely OOM)", conn=conn)
            else:
                await BatchQueue.update_status(
                    conn,
                    batch_id=batch.id,
                    job_state=SourceBatchStatus.State.WAITING_RETRY,
                    attempt=batch.latest_attempt,
                )

    def _install_signal_handlers(self) -> None:
        """Wire SIGTERM/SIGINT to trigger graceful shutdown."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown.set)

    async def _close(self) -> None:
        """Cancel the recovery task, release all advisory locks, and close both connections."""
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            try:
                await self._recovery_task
            except asyncio.CancelledError:
                pass

        if self._recovery_conn is not None and not self._recovery_conn.closed:
            await self._recovery_conn.close()

        if self._conn is not None and not self._conn.closed:
            await self._conn.execute("SELECT pg_advisory_unlock_all()")
            await self._conn.close()

        logger.info("batch_consumer_stopped")


ProcessBatchFn = Callable[[PendingBatch], Coroutine[Any, Any, None]]


def _update_job_status_to_failed(*, job_id: str, team_id: int, error: str) -> None:
    """Sync helper to mark the ExternalDataJob and its schema as failed via Django ORM."""
    from products.data_warehouse.backend.external_data_source.jobs import update_external_job_status
    from products.data_warehouse.backend.models.external_data_job import ExternalDataJob

    existing = ExternalDataJob.objects.filter(id=job_id, team_id=team_id, status=ExternalDataJob.Status.FAILED).first()
    if existing is not None:
        return

    update_external_job_status(
        job_id=job_id,
        team_id=team_id,
        status=ExternalDataJob.Status.FAILED,
        logger=structlog.get_logger(),
        latest_error=error,
    )


def _group_by_key(batches: list[PendingBatch]) -> dict[tuple[int, str], list[PendingBatch]]:
    """Group batches by (team_id, schema_id), preserving insertion order."""
    groups: dict[tuple[int, str], list[PendingBatch]] = defaultdict(list)
    for batch in batches:
        groups[(batch.team_id, batch.schema_id)].append(batch)
    return groups
