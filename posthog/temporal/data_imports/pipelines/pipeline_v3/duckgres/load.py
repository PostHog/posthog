from __future__ import annotations

from asgiref.sync import sync_to_async

from posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor import process_batch as process_sync
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import PendingBatch


async def process_batch(batch: PendingBatch) -> None:
    await sync_to_async(process_sync)(batch)
