"""
Adapter that connects the BatchConsumer to the existing Delta Lake loading logic.

Converts a PendingBatch into an ExportSignalMessage dict and delegates to
process_message(). This exists because ProcessBatchFn expects an async callable
that takes a PendingBatch, but the existing processor works with ExportSignalMessage
dicts. Once process_message is refactored to accept PendingBatch directly, this
adapter and to_export_signal() can be removed.

The BatchConsumer handles retries and status updates around this function — it
only needs to raise on failure.
"""

from __future__ import annotations

from asgiref.sync import sync_to_async

from posthog.temporal.data_imports.pipelines.pipeline_v3.load.processor import process_message
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import PendingBatch


async def process_batch(batch: PendingBatch) -> None:
    """Load a single batch into Delta Lake, reusing the existing processor."""
    await sync_to_async(process_message)(batch.to_export_signal())
