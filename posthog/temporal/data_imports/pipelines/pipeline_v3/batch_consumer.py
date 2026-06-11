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

from posthog.exceptions_capture import capture_exception
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
RETRY_BACKOFF_BASE_SECONDS = 15
HEARTBEAT_INTERVAL_SECONDS = 5.0

# Reconcile sweep: catch runs whose queue batch failed but whose ExternalDataJob was left non-terminal.
RECONCILE_INTERVAL_SECONDS = 300.0
RECONCILE_GRACE_SECONDS = 120  # don't race a _fail_run that is still in flight
RECONCILE_LOOKBACK_SECONDS = 6 * 60 * 60  # keep the queue scan cheap


@dataclass
class BatchConsumerConfig:
    """Tuning knobs for the batch consumer."""

    database_url: str
    max_concurrency: int = 16
    max_attempts: int = MAX_ATTEMPTS
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS
    poll_limit: int = 50
    health_port: int = 8080
    health_timeout_seconds: float = 60.0
    heartbeat_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS
    recovery_interval_seconds: float = RECOVERY_INTERVAL_SECONDS
    retry_backoff_base_seconds: int = RETRY_BACKOFF_BASE_SECONDS
    recovery_grace_seconds: int | None = None
    reconcile_interval_seconds: float = RECONCILE_INTERVAL_SECONDS
    reconcile_grace_seconds: int = RECONCILE_GRACE_SECONDS
    reconcile_lookback_seconds: int = RECONCILE_LOOKBACK_SECONDS
    reconcile_limit: int = 100

    def __post_init__(self) -> None:
        if self.recovery_grace_seconds is None:
            self.recovery_grace_seconds = int(self.recovery_interval_seconds)


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
        retry_backoff_base_seconds: int,
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

    async def get_stale_executing(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int,
    ) -> list[PendingBatch]: ...

    async def reconcile_failed_runs(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int,
        lookback_seconds: int,
        limit: int,
    ) -> None: ...

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
        # Serialize reconnects: concurrent groups all hit _ensure_*_conn on a bounce; without a lock each would dial its own connection and orphan all but the last.
        self._main_conn_lock = asyncio.Lock()
        self._recovery_conn_lock = asyncio.Lock()
        self._recovery_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        # Monotonic stamp of the last reconcile sweep; runs inside the recovery loop so both share one connection.
        self._last_reconcile_monotonic = 0.0

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(
            self._config.database_url,
            autocommit=True,
        )

    async def _ensure_main_conn(self) -> psycopg.AsyncConnection[Any]:
        """Return the main queue connection, reconnecting if a failover/pgbouncer bounce dropped it."""
        if self._conn is not None and not self._conn.closed and not self._conn.broken:
            return self._conn
        async with self._main_conn_lock:
            # Re-check under the lock: another coroutine may have already reconnected while we waited.
            if self._conn is None or self._conn.closed or self._conn.broken:
                logger.warning(self._event("queue_db_main_connection_reconnecting"))
                self._conn = await self._connect()
            return self._conn

    async def _ensure_recovery_conn(self) -> psycopg.AsyncConnection[Any]:
        """Return the recovery/reconcile connection, reconnecting so a dropped one can't disable the sweeps forever."""
        if self._recovery_conn is not None and not self._recovery_conn.closed and not self._recovery_conn.broken:
            return self._recovery_conn
        async with self._recovery_conn_lock:
            if self._recovery_conn is None or self._recovery_conn.closed or self._recovery_conn.broken:
                logger.warning(self._event("queue_db_recovery_connection_reconnecting"))
                self._recovery_conn = await self._connect()
            return self._recovery_conn

    async def _wait_or_shutdown(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._shutdown.wait(), timeout=timeout)
        except TimeoutError:
            pass

    async def run(self) -> None:
        self._install_signal_handlers()

        self._conn = await self._connect()
        self._recovery_conn = await self._connect()

        logger.info(
            self._event("batch_consumer_started"),
            max_concurrency=self._config.max_concurrency,
            poll_interval=self._config.poll_interval_seconds,
            poll_limit=self._config.poll_limit,
        )

        try:
            await self._recovery_sweep()
            self._recovery_task = asyncio.create_task(self._recovery_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            while not self._shutdown.is_set():
                if self._health_reporter:
                    self._health_reporter()

                poll_start = time.monotonic()
                try:
                    conn = await self._ensure_main_conn()
                    batches = await self._adapter.fetch_and_lock(
                        conn,
                        limit=self._config.poll_limit,
                        retry_backoff_base_seconds=self._config.retry_backoff_base_seconds,
                    )
                except psycopg.OperationalError as e:
                    # Queue DB unreachable — keep the pod alive; the next iteration reconnects.
                    logger.exception(self._event("poll_failed_queue_db_unreachable"))
                    capture_exception(e)
                    await self._wait_or_shutdown(self._config.poll_interval_seconds)
                    continue
                POLL_DURATION_SECONDS.observe(time.monotonic() - poll_start)
                POLL_BATCHES_FETCHED.observe(len(batches))

                if not batches:
                    await self._wait_or_shutdown(self._config.poll_interval_seconds)
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
        # Unlock on the session that acquired the advisory locks, even if a reconnect swaps self._conn mid-group.
        lock_conn = self._conn
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
                try:
                    succeeded = await self._process_single(batch)
                except Exception as e:
                    # A queue-DB write failing mid-batch (e.g. stale conn after a bounce) must cost this group, not the pod.
                    logger.exception(
                        self._event("process_single_unhandled_error"),
                        team_id=team_id,
                        external_data_schema_id=schema_id,
                        batch_id=batch.id,
                        batch_index=batch.batch_index,
                    )
                    capture_exception(e)
                    succeeded = False
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
            try:
                assert lock_conn is not None
                await self._adapter.unlock(lock_conn, batches=batches)
            except Exception as e:
                # A dead session already released its locks server-side; don't crash every concurrent group.
                logger.exception(
                    self._event("unlock_for_batches_failed"),
                    team_id=team_id,
                    external_data_schema_id=schema_id,
                )
                capture_exception(e)

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
            "external_data_schema_id",
            "external_data_source_id",
            "external_data_job_id",
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
            external_data_schema_id=batch.schema_id,
            external_data_source_id=batch.source_id,
            external_data_job_id=batch.job_id,
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
        # Check before we even try — if already at max, fail the whole run.
        if attempt > self._config.max_attempts:
            logger.error(
                self._event("batch_max_retries_exceeded"),
                batch_id=batch.id,
                run_uuid=batch.run_uuid,
                attempt=attempt,
            )
            await self._fail_run(batch, reason=f"max retries exceeded (attempt {attempt})")
            return False

        # Pre-increment: if we OOM here, recovery sees attempt=N+1
        # and knows this attempt was consumed.
        await self._adapter.update_status(
            await self._ensure_main_conn(),
            batch_id=batch.id,
            job_state=self._adapter.executing_state,
            attempt=attempt,
        )

        try:
            start = time.monotonic()
            should_process = await self._adapter.should_process_batch(await self._ensure_main_conn(), batch=batch)
            if should_process:
                await self._process_batch(batch)
                await self._adapter.after_batch_processed(await self._ensure_main_conn(), batch=batch)

            BATCH_PROCESSING_DURATION_SECONDS.labels(team_id=team_id, schema_id=schema_id).observe(
                time.monotonic() - start
            )

            await self._adapter.update_status(
                await self._ensure_main_conn(),
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
                capture_exception(err)
                await self._fail_run(batch, reason=f"max retries exceeded: {err}")
            else:
                logger.warning(
                    self._event("batch_failed_will_retry"),
                    batch_id=batch.id,
                    attempt=attempt,
                    error=str(err),
                )
                await self._adapter.update_status(
                    await self._ensure_main_conn(),
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
        """Fail the run via the adapter; the adapter isolates each step so a failure can't crash the consumer."""
        conn = conn or await self._ensure_main_conn()

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
            except Exception as e:
                logger.exception(self._event("recovery_sweep_error"))
                capture_exception(e)

            now = time.monotonic()
            if now - self._last_reconcile_monotonic >= self._config.reconcile_interval_seconds:
                self._last_reconcile_monotonic = now
                try:
                    await self._reconcile_failed_runs()
                except Exception as e:
                    logger.exception(self._event("reconcile_sweep_error"))
                    capture_exception(e)

    async def _reconcile_failed_runs(self) -> None:
        """Reconcile runs whose queue batch failed but whose terminal-state write never landed."""
        conn = await self._ensure_recovery_conn()

        await self._adapter.reconcile_failed_runs(
            conn,
            grace_seconds=self._config.reconcile_grace_seconds,
            lookback_seconds=self._config.reconcile_lookback_seconds,
            limit=self._config.reconcile_limit,
        )

    async def _heartbeat_loop(self) -> None:
        """Report liveness on a fixed cadence, independent of batch processing.

        A poll cycle can run far longer than the health timeout (e.g. large final-batch
        compaction), so the main loop's per-poll health report is not enough on its own.
        """
        while not self._shutdown.is_set():
            if self._health_reporter:
                self._health_reporter()
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=self._config.heartbeat_interval_seconds)
            except TimeoutError:
                pass

    async def _recovery_sweep(self) -> None:
        conn = await self._ensure_recovery_conn()

        grace_seconds = self._config.recovery_grace_seconds
        assert grace_seconds is not None
        stale = await self._adapter.get_stale_executing(conn, grace_seconds=grace_seconds)
        if not stale:
            RECOVERY_SWEEPS_TOTAL.labels(outcome="clean").inc()
            return

        RECOVERY_SWEEPS_TOTAL.labels(outcome="orphans_found").inc()
        logger.info(self._event("recovery_sweep_found_stale_batches"), count=len(stale))

        recovery_bound_keys = (
            "team_id",
            "external_data_schema_id",
            "external_data_source_id",
            "external_data_job_id",
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
                external_data_schema_id=batch.schema_id,
                external_data_source_id=batch.source_id,
                external_data_job_id=batch.job_id,
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
        for task in (self._recovery_task, self._heartbeat_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._recovery_conn is not None and not self._recovery_conn.closed:
            await self._recovery_conn.close()

        if self._conn is not None and not self._conn.closed:
            try:
                await self._conn.execute("SELECT pg_advisory_unlock_all()")
            except Exception as e:
                # A broken session already lost its advisory locks; still close below.
                logger.exception(self._event("advisory_unlock_all_failed_on_shutdown"))
                capture_exception(e)
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
