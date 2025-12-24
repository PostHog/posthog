import json
import datetime as dt
import posixpath
import dataclasses

from django.conf import settings

from azure.storage.blob.aio import BlobServiceClient, ContainerClient
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import (
    AzureBlobBatchExportInputs,
    BatchExportField,
    BatchExportInsertInputs,
    BatchExportModel,
)
from posthog.models.integration import AzureBlobIntegration, Integration
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import (
    OverBillingLimitError,
    StartBatchExportRunInputs,
    events_model_default_fields,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.pipeline.consumer import Consumer, run_consumer_from_stage
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer as ProducerFromInternalStage
from products.batch_exports.backend.temporal.pipeline.transformer import (
    ParquetStreamTransformer,
    get_json_stream_transformer,
)
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, wait_for_schema_or_producer
from products.batch_exports.backend.temporal.utils import handle_non_retryable_errors

NON_RETRYABLE_ERROR_TYPES = (
    "ResourceNotFoundError",
    "ClientAuthenticationError",
    "AzureBlobIntegrationError",
    "AzureBlobIntegrationNotFoundError",
    "UnsupportedFileFormatError",
)

FILE_FORMAT_EXTENSIONS = {
    "Parquet": "parquet",
    "JSONLines": "jsonl",
}

COMPRESSION_EXTENSIONS = {
    "gzip": "gz",
    "brotli": "br",
    "zstd": "zst",
}

SUPPORTED_COMPRESSIONS = {
    "Parquet": ["zstd", "gzip", "brotli"],
    "JSONLines": ["gzip", "brotli"],
}

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")


class UnsupportedFileFormatError(Exception):
    def __init__(self, file_format: str):
        super().__init__(f"'{file_format}' is not a supported format for Azure Blob batch exports.")


class AzureBlobIntegrationNotFoundError(Exception):
    def __init__(self, integration_id: int, team_id: int):
        super().__init__(f"Azure Blob integration with id '{integration_id}' not found for team '{team_id}'")


@dataclasses.dataclass(kw_only=True)
class AzureBlobInsertInputs(BatchExportInsertInputs):
    container_name: str
    prefix: str = ""
    compression: str | None = None
    file_format: str = "JSONLines"
    max_file_size_mb: int | None = None
    integration_id: int


def get_allowed_template_variables(
    data_interval_start: str | None, data_interval_end: str, batch_export_model: BatchExportModel | None
) -> dict[str, str]:
    export_datetime = dt.datetime.fromisoformat(data_interval_end)

    return {
        "second": f"{export_datetime:%S}",
        "minute": f"{export_datetime:%M}",
        "hour": f"{export_datetime:%H}",
        "day": f"{export_datetime:%d}",
        "month": f"{export_datetime:%m}",
        "year": f"{export_datetime:%Y}",
        "data_interval_start": data_interval_start or "START",
        "data_interval_end": data_interval_end,
        "table": batch_export_model.name if batch_export_model is not None else "events",
    }


def get_blob_key_prefix(
    prefix: str, data_interval_start: str | None, data_interval_end: str, batch_export_model: BatchExportModel | None
) -> str:
    template_variables = get_allowed_template_variables(data_interval_start, data_interval_end, batch_export_model)

    try:
        return prefix.format(**template_variables)
    except (KeyError, ValueError) as e:
        EXTERNAL_LOGGER.warning(
            f"The key prefix '{prefix}' will be used as-is since it contains invalid template variables: {str(e)}"
        )
        return prefix


def get_blob_key(
    prefix: str,
    data_interval_start: str | None,
    data_interval_end: str,
    batch_export_model: BatchExportModel | None,
    file_format: str,
    compression: str | None = None,
    file_number: int = 0,
    is_splitting: bool = False,
) -> str:
    key_prefix = get_blob_key_prefix(prefix, data_interval_start, data_interval_end, batch_export_model)

    try:
        file_extension = FILE_FORMAT_EXTENSIONS[file_format]
    except KeyError:
        raise UnsupportedFileFormatError(file_format)

    base_file_name = f"{data_interval_start}-{data_interval_end}"

    if is_splitting:
        base_file_name = f"{base_file_name}-{file_number}"

    if compression is not None:
        file_name = base_file_name + f".{file_extension}.{COMPRESSION_EXTENSIONS[compression]}"
    else:
        file_name = base_file_name + f".{file_extension}"

    key = posixpath.join(key_prefix, file_name)

    if posixpath.isabs(key):
        key = posixpath.relpath(key, "/")

    return key


def get_manifest_key(
    prefix: str, data_interval_start: str | None, data_interval_end: str, batch_export_model: BatchExportModel | None
) -> str:
    key_prefix = get_blob_key_prefix(prefix, data_interval_start, data_interval_end, batch_export_model)
    return posixpath.join(key_prefix, f"{data_interval_start}-{data_interval_end}_manifest.json")


async def _get_azure_blob_integration(integration_id: int, team_id: int) -> AzureBlobIntegration:
    try:
        integration = await Integration.objects.aget(id=integration_id, team_id=team_id)
    except Integration.DoesNotExist:
        raise AzureBlobIntegrationNotFoundError(integration_id, team_id)

    return AzureBlobIntegration(integration)


def azure_blob_default_fields() -> list[BatchExportField]:
    return events_model_default_fields()


@workflow.defn(name="azure-blob-export", failure_exception_types=[workflow.NondeterminismError])
class AzureBlobBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into Azure Blob Storage."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> AzureBlobBatchExportInputs:
        loaded = json.loads(inputs[0])
        return AzureBlobBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: AzureBlobBatchExportInputs):
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

        insert_inputs = AzureBlobInsertInputs(
            container_name=inputs.container_name,
            prefix=inputs.prefix,
            team_id=inputs.team_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            compression=inputs.compression,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            file_format=inputs.file_format,
            max_file_size_mb=inputs.max_file_size_mb,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=azure_blob_default_fields(),
            integration_id=inputs.integration_id,
        )

        await execute_batch_export_using_internal_stage(
            insert_into_azure_blob_activity_from_stage,
            insert_inputs,
            interval=inputs.interval,
        )


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_azure_blob_activity_from_stage(inputs: AzureBlobInsertInputs) -> BatchExportResult:
    bind_contextvars(
        team_id=inputs.team_id,
        destination="AzureBlob",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    azure_integration = await _get_azure_blob_integration(inputs.integration_id, inputs.team_id)

    blob_key = get_blob_key(
        prefix=inputs.prefix,
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        batch_export_model=inputs.batch_export_model,
        file_format=inputs.file_format,
        compression=inputs.compression,
        is_splitting=inputs.max_file_size_mb is not None,
    )

    external_logger.info(
        "Batch exporting range %s - %s to Azure Blob: %s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        blob_key,
    )

    async with Heartbeater():
        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_AZURE_BLOB_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = ProducerFromInternalStage()

        assert inputs.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 60,  # 60MB
            stage_folder=inputs.stage_folder,
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )
            return BatchExportResult(records_completed=0, bytes_exported=0)

        consumer = await AzureBlobConsumer.from_inputs(
            inputs=inputs,
            connection_string=azure_integration.connection_string,
            max_concurrency=settings.BATCH_EXPORT_AZURE_BLOB_MAX_CONCURRENT_UPLOADS,
        )

        json_columns = ("properties", "person_properties", "set", "set_once")
        if inputs.file_format.lower() == "jsonlines":
            transformer = get_json_stream_transformer(
                compression=inputs.compression,
                include_inserted_at=True,
                max_file_size_bytes=inputs.max_file_size_mb * 1024 * 1024 if inputs.max_file_size_mb else 0,
            )
        else:
            transformer = ParquetStreamTransformer(
                compression=inputs.compression,
                include_inserted_at=True,
                max_file_size_bytes=inputs.max_file_size_mb * 1024 * 1024 if inputs.max_file_size_mb else 0,
            )

        return await run_consumer_from_stage(
            queue=queue,
            consumer=consumer,
            producer_task=producer_task,
            transformer=transformer,
            json_columns=json_columns,
        )


class AzureBlobConsumer(Consumer):
    """Consumer that uploads data to Azure Blob Storage."""

    def __init__(
        self,
        container_client: ContainerClient,
        prefix: str,
        data_interval_start: str | None,
        data_interval_end: str,
        batch_export_model: BatchExportModel | None,
        file_format: str,
        compression: str | None = None,
        max_file_size_mb: int | None = None,
        max_concurrency: int = 5,
    ):
        super().__init__()

        self.container_client = container_client
        self.prefix = prefix
        self.data_interval_start = data_interval_start
        self.data_interval_end = data_interval_end
        self.batch_export_model = batch_export_model
        self.file_format = file_format
        self.compression = compression
        self.max_file_size_mb = max_file_size_mb
        self.max_concurrency = max_concurrency

        self.current_buffer = bytearray()
        self.current_file_index = 0
        self.files_uploaded: list[str] = []

    @classmethod
    async def from_inputs(
        cls,
        inputs: AzureBlobInsertInputs,
        connection_string: str,
        max_concurrency: int,
    ) -> "AzureBlobConsumer":
        # Blobs larger than `max_single_put_size` are uploaded in blocks of `max_block_size`.
        # These are Azure SDK defaults but we set them explicitly for visibility.
        # See: https://learn.microsoft.com/en-us/python/api/azure-storage-blob/azure.storage.blob.blobserviceclient
        blob_service_client = BlobServiceClient.from_connection_string(
            conn_str=connection_string,
            max_single_put_size=64 * 1024 * 1024,  # 64 MiB
            max_block_size=4 * 1024 * 1024,  # 4 MiB
        )
        container_client = blob_service_client.get_container_client(inputs.container_name)

        return cls(
            container_client=container_client,
            prefix=inputs.prefix,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            batch_export_model=inputs.batch_export_model,
            file_format=inputs.file_format,
            compression=inputs.compression,
            max_file_size_mb=inputs.max_file_size_mb,
            max_concurrency=max_concurrency,
        )

    def _get_current_blob_key(self) -> str:
        return get_blob_key(
            prefix=self.prefix,
            data_interval_start=self.data_interval_start,
            data_interval_end=self.data_interval_end,
            batch_export_model=self.batch_export_model,
            file_format=self.file_format,
            compression=self.compression,
            file_number=self.current_file_index,
            is_splitting=self.max_file_size_mb is not None,
        )

    async def consume_chunk(self, data: bytes):
        self.current_buffer.extend(data)

    async def finalize_file(self):
        await self._upload_current_buffer()
        self.current_file_index += 1

    async def finalize(self):
        if self.current_buffer:
            await self._upload_current_buffer()

        if self.max_file_size_mb and len(self.files_uploaded) > 1:
            await self._upload_manifest()

        await self.container_client.close()

    async def _upload_current_buffer(self):
        if not self.current_buffer:
            return

        blob_key = self._get_current_blob_key()
        blob_client = self.container_client.get_blob_client(blob_key)

        self.logger.debug("blob_upload_started", blob_key=blob_key, size_bytes=len(self.current_buffer))

        await blob_client.upload_blob(
            bytes(self.current_buffer),
            overwrite=True,
            max_concurrency=self.max_concurrency,
        )

        self.logger.debug("blob_upload_completed", blob_key=blob_key)
        self.files_uploaded.append(blob_key)
        self.current_buffer.clear()

    async def _upload_manifest(self):
        manifest_key = get_manifest_key(
            prefix=self.prefix,
            data_interval_start=self.data_interval_start,
            data_interval_end=self.data_interval_end,
            batch_export_model=self.batch_export_model,
        )
        manifest_content = json.dumps({"files": self.files_uploaded}, indent=2)

        blob_client = self.container_client.get_blob_client(manifest_key)
        await blob_client.upload_blob(
            manifest_content.encode("utf-8"),
            overwrite=True,
        )
        self.logger.info("manifest_uploaded", manifest_key=manifest_key, file_count=len(self.files_uploaded))
