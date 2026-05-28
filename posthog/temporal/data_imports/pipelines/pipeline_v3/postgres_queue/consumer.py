"""
Postgres-backed batch consumer for warehouse source loading.

This module preserves the Delta consumer import path while delegating the shared
polling, retry, and recovery mechanics to the v3 batch consumer engine.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg
import structlog
from asgiref.sync import sync_to_async

from posthog.temporal.data_imports.pipelines.pipeline_v3.batch_consumer import (
    MAX_ATTEMPTS,
    POLL_INTERVAL_SECONDS,
    RECOVERY_INTERVAL_SECONDS,
    BatchConsumer as SharedBatchConsumer,
    BatchConsumerConfig,
    ProcessBatchFn,
    _group_by_key,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import BatchQueue, PendingBatch

from products.data_warehouse.backend.external_data_source.jobs import update_external_job_status
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources_queue.backend.models import SourceBatchStatus

logger = structlog.get_logger(__name__)

ConsumerConfig = BatchConsumerConfig


class DeltaBatchConsumerAdapter:
    log_prefix: str = ""
    executing_state: str = SourceBatchStatus.State.EXECUTING.value
    succeeded_state: str = SourceBatchStatus.State.SUCCEEDED.value
    waiting_retry_state: str = SourceBatchStatus.State.WAITING_RETRY.value

    async def fetch_and_lock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int,
    ) -> list[PendingBatch]:
        return await BatchQueue.get_unprocessed_and_lock(conn, limit=limit)

    async def unlock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batches: list[PendingBatch],
    ) -> None:
        await BatchQueue.unlock_for_batches(conn, batches=batches)

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
            await BatchQueue.update_status(
                conn,
                batch_id=batch_id,
                job_state=job_state,
                attempt=attempt,
            )
            return

        await BatchQueue.update_status(
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
        await BatchQueue.fail_run(conn, run_uuid=batch.run_uuid, reason=reason)
        await sync_to_async(_update_job_status_to_failed)(
            job_id=batch.job_id,
            team_id=batch.team_id,
            error=reason,
        )

    async def get_stale_executing(self, conn: psycopg.AsyncConnection[Any]) -> list[PendingBatch]:
        return await BatchQueue.get_stale_executing(conn)

    async def should_process_batch(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> bool:
        return True

    async def after_batch_processed(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> None:
        return None


class BatchConsumer(SharedBatchConsumer):
    def __init__(
        self,
        config: ConsumerConfig,
        process_batch: ProcessBatchFn,
        health_reporter: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            config=config,
            process_batch=process_batch,
            adapter=DeltaBatchConsumerAdapter(),
            health_reporter=health_reporter,
        )


def _update_job_status_to_failed(*, job_id: str, team_id: int, error: str) -> None:
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


__all__ = [
    "BatchConsumer",
    "ConsumerConfig",
    "DeltaBatchConsumerAdapter",
    "MAX_ATTEMPTS",
    "POLL_INTERVAL_SECONDS",
    "ProcessBatchFn",
    "RECOVERY_INTERVAL_SECONDS",
    "_group_by_key",
]
