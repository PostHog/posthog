import json
import logging
import datetime as dt
import collections.abc
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings

import pyarrow as pa
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import BackfillDetails, BatchExportInsertInputs, NoOpBatchExportInputs, NoOpInputs
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import (
    OverBillingLimitError,
    StartBatchExportRunInputs,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.pipeline.consumer import Consumer
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.pipeline.transformer import Chunk
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, wait_for_schema_or_producer

LOGGER = get_write_only_logger(__name__)


@dataclass
class NoopActivityArgs:
    arg: str
    backfill_details: BackfillDetails | None = None


@activity.defn
async def noop_activity(inputs: NoopActivityArgs) -> str:
    activity.logger.info(f"Running activity with parameter {inputs.arg}")
    output = f"OK - {inputs.arg}"
    logging.warning(f"[Action] - Action executed on worker with output: {output}")
    return output


@workflow.defn(name="no-op")
class NoOpWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> Any:
        """Parse inputs from the management command CLI.

        We expect only one input, so we just return it and assume it's correct.
        """
        loaded = json.loads(inputs[0])
        return NoOpInputs(**loaded)

    @workflow.run
    async def run(self, inputs: NoOpInputs) -> str:
        workflow.logger.info(f"Running workflow with parameter {inputs.arg}")
        result = await workflow.execute_activity(
            noop_activity,
            NoopActivityArgs(inputs.arg, inputs.backfill_details),
            start_to_close_timeout=timedelta(seconds=60),
            schedule_to_close_timeout=timedelta(minutes=5),
        )
        logging.warning(f"[Workflow] - Workflow executed on worker with output: {result}")
        return result


# --- NoOp Batch Export Workflow ---
# This workflow follows the full batch export pattern with execute_batch_export_using_internal_stage
# and properly reports records_completed for backfill tracking.


@dataclass
class NoOpInsertInputs(BatchExportInsertInputs):
    """Inputs for NoOp batch export insert activity."""

    pass


class NoOpTransformer:
    """A transformer that yields empty chunks while preserving EOF signals.

    This transformer iterates through all record batches (so they get counted)
    but doesn't actually transform them into any output format.
    """

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch]
    ) -> collections.abc.AsyncIterator[Chunk]:
        async for _ in record_batches:
            yield Chunk(data=b"", is_eof=False)
        yield Chunk(data=b"", is_eof=True)


class NoOpConsumer(Consumer):
    """A consumer that does nothing with the chunks.

    The base Consumer class handles record counting via track_record_batch,
    so we just need to implement the abstract methods as no-ops.
    """

    async def consume_chunk(self, data: bytes) -> None:
        pass

    async def finalize_file(self) -> None:
        pass

    async def finalize(self) -> None:
        pass


@activity.defn
async def insert_into_noop_activity_from_stage(inputs: NoOpInsertInputs) -> BatchExportResult:
    """Activity that reads from internal stage and counts records without writing anywhere.

    This activity follows the same pattern as other batch export insert activities
    (like insert_into_s3_activity_from_stage) but doesn't actually export data.
    It's useful for testing the batch export pipeline.
    """
    bind_contextvars(
        team_id=inputs.team_id,
        destination="NoOp",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
    )

    logger = LOGGER.bind()
    logger.info(
        "NoOp batch export for range %s - %s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
    )

    async with Heartbeater():
        queue: RecordBatchQueue = RecordBatchQueue(
            max_size_bytes=settings.BATCH_EXPORT_S3_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES
        )
        producer = Producer()
        assert inputs.batch_export_id is not None

        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 10,  # 10MB
            stage_folder=inputs.stage_folder,
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            logger.info(
                "NoOp batch export finishing early - no data in range %s - %s",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )
            return BatchExportResult(records_completed=0, bytes_exported=0)

        consumer = NoOpConsumer()
        transformer = NoOpTransformer()

        result = await consumer.start(
            queue=queue,
            producer_task=producer_task,
            transformer=transformer,
        )

        logger.info(
            "NoOp batch export completed with %s records",
            result.records_completed,
        )
        return result


@workflow.defn(name="no-op-export")
class NoOpBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow for testing that follows the full batch export pattern.

    Unlike the simple NoOpWorkflow, this workflow uses execute_batch_export_using_internal_stage
    and properly reports records_completed for backfill tracking.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> NoOpBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return NoOpBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: NoOpBatchExportInputs) -> None:
        """Workflow implementation for NoOp batch export."""
        is_backfill = inputs.get_is_backfill()
        is_earliest_backfill = inputs.get_is_earliest_backfill()
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)
        should_backfill_from_beginning = is_backfill and is_earliest_backfill

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            backfill_id=inputs.backfill_details.backfill_id if inputs.backfill_details else None,
        )

        try:
            run_id = await workflow.execute_activity(
                start_batch_export_run,
                start_batch_export_run_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError", "OverBillingLimitError"],
                ),
            )
        except OverBillingLimitError:
            return

        insert_inputs = NoOpInsertInputs(
            team_id=inputs.team_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            batch_export_id=inputs.batch_export_id,
        )

        await execute_batch_export_using_internal_stage(
            insert_into_noop_activity_from_stage,
            insert_inputs,
            interval=inputs.interval,
        )
