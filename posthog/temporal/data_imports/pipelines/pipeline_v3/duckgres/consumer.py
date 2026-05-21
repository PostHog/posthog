from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg

from posthog.temporal.data_imports.pipelines.pipeline_v3.batch_consumer import (
    MAX_ATTEMPTS,
    POLL_INTERVAL_SECONDS,
    RECOVERY_INTERVAL_SECONDS,
    BatchConsumer as SharedBatchConsumer,
    BatchConsumerConfig,
    ProcessBatchFn,
    _group_by_key,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.jobs_db import DuckgresBatchQueue
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import PendingBatch

from products.warehouse_sources_queue.backend.models import SourceBatchDuckgresStatus

DuckgresConsumerConfig = BatchConsumerConfig


class DuckgresBatchConsumerAdapter:
    log_prefix: str = "duckgres"
    executing_state: str = SourceBatchDuckgresStatus.State.EXECUTING.value
    succeeded_state: str = SourceBatchDuckgresStatus.State.SUCCEEDED.value
    waiting_retry_state: str = SourceBatchDuckgresStatus.State.WAITING_RETRY.value

    async def fetch_and_lock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int,
    ) -> list[PendingBatch]:
        return await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn, limit=limit)

    async def unlock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batches: list[PendingBatch],
    ) -> None:
        await DuckgresBatchQueue.unlock_for_batches(conn, batches=batches)

    async def update_status(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
        job_state: str,
        attempt: int,
        error_response: dict[str, Any] | None = None,
    ) -> None:
        if error_response is None:
            await DuckgresBatchQueue.update_status(
                conn,
                batch_id=batch_id,
                job_state=job_state,
                attempt=attempt,
            )
            return

        await DuckgresBatchQueue.update_status(
            conn,
            batch_id=batch_id,
            job_state=job_state,
            attempt=attempt,
            error_response=error_response,
        )

    async def fail_run(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
        reason: str,
    ) -> None:
        await DuckgresBatchQueue.fail_run(conn, run_uuid=batch.run_uuid, reason=reason)

    async def get_stale_executing(self, conn: psycopg.AsyncConnection[Any]) -> list[PendingBatch]:
        return await DuckgresBatchQueue.get_stale_executing(conn)

    async def should_process_batch(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> bool:
        already_applied = await DuckgresBatchQueue.has_applied(conn, batch=batch)
        if batch.is_final_batch:
            if not already_applied:
                raise RuntimeError(f"Final Duckgres marker received before batch {batch.batch_index} was applied")
            return False
        return not already_applied

    async def after_batch_processed(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> None:
        if not batch.is_final_batch:
            await DuckgresBatchQueue.mark_applied(conn, batch=batch)


class DuckgresBatchConsumer(SharedBatchConsumer):
    def __init__(
        self,
        config: DuckgresConsumerConfig,
        process_batch: ProcessBatchFn,
        health_reporter: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            config=config,
            process_batch=process_batch,
            adapter=DuckgresBatchConsumerAdapter(),
            health_reporter=health_reporter,
        )


__all__ = [
    "DuckgresBatchConsumer",
    "DuckgresBatchConsumerAdapter",
    "DuckgresConsumerConfig",
    "MAX_ATTEMPTS",
    "POLL_INTERVAL_SECONDS",
    "RECOVERY_INTERVAL_SECONDS",
    "_group_by_key",
]
