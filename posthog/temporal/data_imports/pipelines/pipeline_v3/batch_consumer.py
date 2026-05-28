from __future__ import annotations

import time
import signal
import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Protocol

import psycopg
import structlog

from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import PendingBatch
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

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS = 3
POLL_INTERVAL_SECONDS = 2.0
RECOVERY_INTERVAL_SECONDS = 30.0


@dataclass
class BatchConsumerConfig:
    database_url: str
    max_concurrency: int = 16
    max_attempts: int = MAX_ATTEMPTS
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS
    poll_limit: int = 50
    health_port: int = 8080
    health_timeout_seconds: float = 60.0
    recovery_interval_seconds: float = RECOVERY_INTERVAL_SECONDS


class BatchConsumerAdapter(Protocol):
    log_prefix: str
    executing_state: str
    succeeded_state: str
    waiting_retry_state: str

    async def fetch_and_lock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int,
    ) -> list[PendingBatch]: ...

    async def unlock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batches: list[PendingBatch],
    ) -> None: ...

    async def update_status(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
        job_state: str,
        attempt: int,
        error_response: dict[str, Any] | None = None,
    ) -> None: ...

    async def fail_run(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
        reason: str,
    ) -> None: ...

    async def get_stale_executing(self, conn: psycopg.AsyncConnection[Any]) -> list[PendingBatch]: ...

    async def should_process_batch(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> bool: ...

    async def after_batch_processed(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> None: ...


class BatchConsumer:
    def __init__(
        self,
        config: BatchConsumerConfig,
        process_batch: ProcessBatchFn,
        adapter: BatchConsumerAdapter,
        health_reporter: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._process_batch = process_batch
        self._adapter = adapter
        self._health_reporter = health_reporter
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self._shutdown = asyncio.Event()
        self._conn: psycopg.AsyncConnection[Any] | None = None
        self._recovery_conn: psycopg.AsyncConnection[Any] | None = None
        self._recovery_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        self._install_signal_handlers()

        self._conn = await psycopg.AsyncConnection.connect(self._config.database_url, autocommit=True)
        self._recovery_conn = await psycopg.AsyncConnection.connect(self._config.database_url, autocommit=True)

        logger.info(
            self._event("batch_consumer_started"),
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
                batches = await self._adapter.fetch_and_lock(
                    self._conn,
                    limit=self._config.poll_limit,
                )
                POLL_DURATION_SECONDS.observe(time.monotonic() - poll_start)
                POLL_BATCHES_FETCHED.observe(len(batches))

                if not batches:
                    try:
                        await asyncio.wait_for(self._shutdown.wait(), timeout=self._config.poll_interval_seconds)
                    except TimeoutError:
                        pass
                    continue

                groups = _group_by_key(batches)

                logger.debug(
                    self._event("poll_returned"),
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

    async def _process_group(self, key: tuple[int, str], batches: list[PendingBatch]) -> None:
        team_id, schema_id = key
        await self._semaphore.acquire()
        try:
            for batch in batches:
                if self._shutdown.is_set():
                    logger.info(
                        self._event("shutdown_mid_group"),
                        team_id=team_id,
                        schema_id=schema_id,
                        remaining=len(batches) - batches.index(batch),
                    )
                    break
                succeeded = await self._process_single(batch)
                if not succeeded:
                    # Stop processing sibling batches in this run once one fails or
                    # enters waiting_retry — later batches depend on earlier ones.
                    logger.info(
                        self._event("group_halted_by_non_success"),
                        team_id=team_id,
                        schema_id=schema_id,
                        run_uuid=batch.run_uuid,
                        remaining=len(batches) - batches.index(batch) - 1,
                    )
                    break
        finally:
            self._semaphore.release()
            assert self._conn is not None
            await self._adapter.unlock(self._conn, batches=batches)

    async def _process_single(self, batch: PendingBatch) -> bool:
        """Bind per-batch log context, then process. Returns True only on success.

        Binds structlog contextvars so every downstream log line (including loader calls)
        routes to log_entries under the right schema/workflow before any logger fires.
        """
        team_id = str(batch.team_id)
        schema_id = batch.schema_id
        attempt = batch.latest_attempt + 1

        # Producer (running inside a Temporal activity) stamps workflow ids into batch metadata,
        # so no DB round-trip is needed here. Derive workflow_type from the workflow_id prefix so
        # non-CDC syncs (regular `external-data-job`) route to the right `log_entries` source too.
        workflow_id = batch.metadata.get("workflow_id") or ""
        workflow_run_id = batch.metadata.get("workflow_run_id") or ""
        workflow_type = "cdc-extraction" if workflow_id.startswith("cdc-extraction-") else "external-data-job"

        bound_keys = (
            "team_id",
            "schema_id",
            "source_id",
            "job_id",
            "run_uuid",
            "batch_id",
            "resource_name",
            "workflow_type",
            "workflow_id",
            "workflow_run_id",
            "log_source_id",
            "attempt",
        )
        structlog.contextvars.bind_contextvars(
            team_id=batch.team_id,
            schema_id=batch.schema_id,
            source_id=batch.source_id,
            job_id=batch.job_id,
            run_uuid=batch.run_uuid,
            batch_id=batch.id,
            resource_name=batch.resource_name,
            workflow_type=workflow_type,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            log_source_id=batch.schema_id,
            attempt=attempt,
        )
        try:
            return await self._process_single_inner(batch, attempt, team_id, schema_id)
        finally:
            # Unbind only the keys we set so ambient context (parent logger, test setup) survives.
            structlog.contextvars.unbind_contextvars(*bound_keys)

    async def _process_single_inner(self, batch: PendingBatch, attempt: int, team_id: str, schema_id: str) -> bool:
        assert self._conn is not None

        if attempt > self._config.max_attempts:
            logger.error(
                self._event("batch_max_retries_exceeded"),
                batch_id=batch.id,
                run_uuid=batch.run_uuid,
                attempt=attempt,
            )
            await self._fail_run(batch, reason=f"max retries exceeded (attempt {attempt})")
            return False

        await self._adapter.update_status(
            self._conn,
            batch_id=batch.id,
            job_state=self._adapter.executing_state,
            attempt=attempt,
        )

        try:
            start = time.monotonic()
            should_process = await self._adapter.should_process_batch(self._conn, batch=batch)
            if should_process:
                await self._process_batch(batch)
                await self._adapter.after_batch_processed(self._conn, batch=batch)

            BATCH_PROCESSING_DURATION_SECONDS.labels(team_id=team_id, schema_id=schema_id).observe(
                time.monotonic() - start
            )

            await self._adapter.update_status(
                self._conn,
                batch_id=batch.id,
                job_state=self._adapter.succeeded_state,
                attempt=attempt,
            )
            BATCHES_PROCESSED_TOTAL.labels(team_id=team_id, schema_id=schema_id, status="success").inc()
            return True
        except Exception as err:
            BATCHES_PROCESSED_TOTAL.labels(team_id=team_id, schema_id=schema_id, status="error").inc()
            BATCH_RETRY_TOTAL.labels(attempt=str(attempt), error_type=type(err).__name__).inc()

            if attempt >= self._config.max_attempts:
                logger.exception(
                    self._event("batch_failed_no_retries_left"),
                    batch_id=batch.id,
                    run_uuid=batch.run_uuid,
                    attempt=attempt,
                )
                await self._fail_run(batch, reason=f"max retries exceeded: {err}")
            else:
                logger.warning(
                    self._event("batch_failed_will_retry"),
                    batch_id=batch.id,
                    attempt=attempt,
                    error=str(err),
                )
                await self._adapter.update_status(
                    self._conn,
                    batch_id=batch.id,
                    job_state=self._adapter.waiting_retry_state,
                    attempt=attempt,
                    error_response={"error": str(err)[:1000]},
                )
            return False

    async def _fail_run(
        self,
        batch: PendingBatch,
        reason: str,
        conn: psycopg.AsyncConnection[Any] | None = None,
    ) -> None:
        conn = conn or self._conn
        assert conn is not None

        await self._adapter.fail_run(conn, batch=batch, reason=reason)
        RUNS_FAILED_TOTAL.inc()

    async def _recovery_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=self._config.recovery_interval_seconds)
            except TimeoutError:
                pass

            if self._shutdown.is_set():
                break

            try:
                await self._recovery_sweep()
            except Exception:
                logger.exception(self._event("recovery_sweep_error"))

    async def _recovery_sweep(self) -> None:
        conn = self._recovery_conn or self._conn
        assert conn is not None

        stale = await self._adapter.get_stale_executing(conn)
        if not stale:
            RECOVERY_SWEEPS_TOTAL.labels(outcome="clean").inc()
            return

        RECOVERY_SWEEPS_TOTAL.labels(outcome="orphans_found").inc()
        logger.info(self._event("recovery_sweep_found_stale_batches"), count=len(stale))

        recovery_bound_keys = (
            "team_id",
            "schema_id",
            "source_id",
            "job_id",
            "run_uuid",
            "batch_id",
            "resource_name",
            "log_source_id",
            "attempt",
        )
        for batch in stale:
            # latest_attempt was already incremented before the crash (pre-increment in
            # _process_single), so no +1 needed here.
            structlog.contextvars.bind_contextvars(
                team_id=batch.team_id,
                schema_id=batch.schema_id,
                source_id=batch.source_id,
                job_id=batch.job_id,
                run_uuid=batch.run_uuid,
                batch_id=batch.id,
                resource_name=batch.resource_name,
                log_source_id=batch.schema_id,
                attempt=batch.latest_attempt,
            )
            try:
                if batch.latest_attempt >= self._config.max_attempts:
                    logger.warning(self._event("batch_recovered_max_retries_exceeded"), attempt=batch.latest_attempt)
                    await self._fail_run(batch, reason="max retries exceeded (likely OOM)", conn=conn)
                else:
                    logger.warning(self._event("batch_recovered_for_retry"), attempt=batch.latest_attempt)
                    await self._adapter.update_status(
                        conn,
                        batch_id=batch.id,
                        job_state=self._adapter.waiting_retry_state,
                        attempt=batch.latest_attempt,
                        error_response={"error": "executing timed out — pod restart or OOM"},
                    )
            finally:
                structlog.contextvars.unbind_contextvars(*recovery_bound_keys)

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown.set)

    async def _close(self) -> None:
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

        logger.info(self._event("batch_consumer_stopped"))

    def _event(self, name: str) -> str:
        if not self._adapter.log_prefix:
            return name
        return f"{self._adapter.log_prefix}_{name}"


ProcessBatchFn = Callable[[PendingBatch], Coroutine[Any, Any, None]]


def _group_by_key(batches: list[PendingBatch]) -> dict[tuple[int, str], list[PendingBatch]]:
    groups: dict[tuple[int, str], list[PendingBatch]] = defaultdict(list)
    for batch in batches:
        groups[(batch.team_id, batch.schema_id)].append(batch)
    return groups
