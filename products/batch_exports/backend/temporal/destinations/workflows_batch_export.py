import ssl
import json
import datetime as dt
import dataclasses
import collections.abc

from django.conf import settings

import aiokafka
import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import BatchExportField, BatchExportInsertInputs, WorkflowsBatchExportInputs
from posthog.kafka_client.topics import KAFKA_CDP_BACKFILL_EVENTS
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import (
    OverBillingLimitError,
    StartBatchExportRunInputs,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.pipeline.consumer import Consumer, run_consumer_from_stage
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.pipeline.transformer import JSONLStreamTransformer
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, wait_for_schema_or_producer
from products.batch_exports.backend.temporal.utils import handle_non_retryable_errors

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")

NON_RETRYABLE_ERROR_TYPES: list[str] = []


def workflows_default_fields(batch_export_id: str) -> list[BatchExportField]:
    return [
        BatchExportField(expression="toString(uuid)", alias="uuid"),
        BatchExportField(expression="event", alias="event"),
        BatchExportField(expression="timestamp", alias="_inserted_at"),
        BatchExportField(expression="timestamp", alias="timestamp"),
        BatchExportField(expression="distinct_id", alias="distinct_id"),
        BatchExportField(expression="toString(person_id)", alias="person_id"),
        BatchExportField(expression="team_id", alias="project_id"),
        BatchExportField(expression="team_id", alias="team_id"),
        BatchExportField(expression="created_at", alias="created_at"),
        BatchExportField(expression="elements_chain", alias="elements_chain"),
        BatchExportField(expression="properties", alias="properties"),
        BatchExportField(expression="person_properties", alias="person_properties"),
        BatchExportField(expression="person_created_at", alias="person_created_at"),
        BatchExportField(expression="group0_properties", alias="group0_properties"),
        BatchExportField(expression="group1_properties", alias="group1_properties"),
        BatchExportField(expression="group2_properties", alias="group2_properties"),
        BatchExportField(expression="group3_properties", alias="group3_properties"),
        BatchExportField(expression="group4_properties", alias="group4_properties"),
        BatchExportField(expression="group0_created_at", alias="group0_created_at"),
        BatchExportField(expression="group1_created_at", alias="group1_created_at"),
        BatchExportField(expression="group2_created_at", alias="group2_created_at"),
        BatchExportField(expression="group3_created_at", alias="group3_created_at"),
        BatchExportField(expression="group4_created_at", alias="group4_created_at"),
        BatchExportField(expression=f"'{batch_export_id}'", alias="batch_export_id"),
    ]


def configure_default_ssl_context():
    """Setup a default SSL context for Kafka."""
    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_OPTIONAL
    context.load_default_certs()
    return context


class WorkflowsConsumer(Consumer):
    def __init__(
        self,
        topic: str,
        hosts: collections.abc.Sequence[str],
        security_protocol: str = "PLAINTEXT",
    ):
        super().__init__()
        self.producer = aiokafka.AIOKafkaProducer(
            bootstrap_servers=hosts,
            security_protocol=security_protocol,
            api_version="2.5.0",
            acks="all",
            enable_idempotence=True,
            compression_type="zstd",
            ssl_context=configure_default_ssl_context() if security_protocol == "SSL" else None,
        )
        self.topic = topic
        self._started = False

    async def consume_chunk(self, data: bytes):
        if not self._started:
            await self.producer.start()
            self._started = True

        await self.producer.send_and_wait(topic=self.topic, value=data)

    async def finalize_file(self):
        """Required by consumer interface."""
        pass

    async def finalize(self):
        await self.producer.flush()
        await self.producer.stop()


@dataclasses.dataclass
class WorkflowsInsertInputs:
    """Inputs for Workflows."""

    batch_export: BatchExportInsertInputs
    topic: str


@temporalio.activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_kafka_activity_from_stage(inputs: WorkflowsInsertInputs) -> BatchExportResult:
    bind_contextvars(
        team_id=inputs.batch_export.team_id,
        destination="Workflows",
        data_interval_start=inputs.batch_export.data_interval_start,
        data_interval_end=inputs.batch_export.data_interval_end,
    )
    external_logger = EXTERNAL_LOGGER.bind()
    external_logger.info(
        "Batch exporting range %s - %s to Workflows in topic: '%s'",
        inputs.batch_export.data_interval_start or "START",
        inputs.batch_export.data_interval_end or "END",
        inputs.topic,
    )

    async with Heartbeater():
        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_KAFKA_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = Producer()
        assert inputs.batch_export.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export.batch_export_id,
            data_interval_start=inputs.batch_export.data_interval_start,
            data_interval_end=inputs.batch_export.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 60,  # 60MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.batch_export.data_interval_start or "START",
                inputs.batch_export.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=0, bytes_exported=0)

        transformer = JSONLStreamTransformer(max_workers=1)
        consumer = WorkflowsConsumer(
            topic=inputs.topic or KAFKA_CDP_BACKFILL_EVENTS,
            hosts=settings.KAFKA_HOSTS,
            security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
        )
        result = await run_consumer_from_stage(
            queue=queue,
            consumer=consumer,
            producer_task=producer_task,
            transformer=transformer,
        )

        return result


@temporalio.workflow.defn(name="workflows-export", failure_exception_types=[temporalio.workflow.NondeterminismError])
class WorkflowsBatchExportWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> "WorkflowsBatchExportWorkflow":
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return WorkflowsBatchExportWorkflow(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: WorkflowsBatchExportInputs):
        """Workflow implementation to export data to BigQuery."""
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
            run_id = await temporalio.workflow.execute_activity(
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

        batch_export_inputs = BatchExportInsertInputs(
            team_id=inputs.team_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=workflows_default_fields(inputs.batch_export_id),
        )

        insert_inputs = WorkflowsInsertInputs(
            batch_export=batch_export_inputs,
            topic=inputs.topic,
        )

        await execute_batch_export_using_internal_stage(
            insert_into_kafka_activity_from_stage,
            insert_inputs,  # type: ignore[arg-type]
            interval=inputs.interval,
            is_workflows=True,
        )
