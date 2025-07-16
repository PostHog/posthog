import asyncio
import dataclasses
import datetime as dt
import json
import posixpath
import typing

import aioboto3
import botocore.exceptions
import pyarrow as pa
from aiobotocore.config import AioConfig
from aiobotocore.session import ClientCreatorContext

if typing.TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client
    from types_aiobotocore_s3.type_defs import (
        CompletedPartTypeDef,
        UploadPartOutputTypeDef,
    )

from django.conf import settings
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportInsertInputs,
    S3BatchExportInputs,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import (
    bind_contextvars,
    get_external_logger,
    get_logger,
)
from products.batch_exports.backend.temporal.batch_exports import (
    RecordsCompleted,
    StartBatchExportRunInputs,
    default_fields,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.metrics import ExecutionTimeRecorder
from products.batch_exports.backend.temporal.pipeline.consumer import (
    Consumer as ConsumerFromStage,
    run_consumer_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.entrypoint import (
    execute_batch_export_using_internal_stage,
)
from products.batch_exports.backend.temporal.pipeline.producer import (
    Producer as ProducerFromInternalStage,
)
from products.batch_exports.backend.temporal.spmc import (
    RecordBatchQueue,
    wait_for_schema_or_producer,
)
from products.batch_exports.backend.temporal.temporary_file import (
    UnsupportedFileFormatError,
)

NON_RETRYABLE_ERROR_TYPES = [
    # S3 parameter validation failed.
    "ParamValidationError",
    # This error usually indicates credentials are incorrect or permissions are missing.
    "ClientError",
    # An S3 bucket doesn't exist.
    "NoSuchBucket",
    # Couldn't connect to custom S3 endpoint
    "EndpointConnectionError",
    # User provided an invalid S3 key
    "InvalidS3Key",
    # All consumers failed with non-retryable errors.
    "RecordBatchConsumerNonRetryableExceptionGroup",
    # Invalid S3 endpoint URL
    "InvalidS3EndpointError",
    # Invalid file_format input
    "UnsupportedFileFormatError",
]

FILE_FORMAT_EXTENSIONS = {
    "Parquet": "parquet",
    "JSONLines": "jsonl",
}

COMPRESSION_EXTENSIONS = {
    "gzip": "gz",
    "snappy": "sz",
    "brotli": "br",
    "zstd": "zst",
    "lz4": "lz4",
}

SUPPORTED_COMPRESSIONS = {
    "Parquet": ["zstd", "lz4", "snappy", "gzip", "brotli"],
    "JSONLines": ["gzip", "brotli"],
}

LOGGER = get_logger(__name__)
EXTERNAL_LOGGER = get_external_logger()


@dataclasses.dataclass(kw_only=True)
class S3InsertInputs(BatchExportInsertInputs):
    """Inputs for S3 exports."""

    # TODO: do _not_ store credentials in temporal inputs. It makes it very hard
    # to keep track of where credentials are being stored and increases the
    # attach surface for credential leaks.

    bucket_name: str
    region: str
    prefix: str
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    compression: str | None = None
    encryption: str | None = None
    kms_key_id: str | None = None
    endpoint_url: str | None = None
    # TODO: In Python 3.11, this could be a enum.StrEnum.
    file_format: str = "JSONLines"
    max_file_size_mb: int | None = None
    use_virtual_style_addressing: bool = False


def get_allowed_template_variables(inputs) -> dict[str, str]:
    """Derive from inputs a dictionary of supported template variables for the S3 key prefix."""
    export_datetime = dt.datetime.fromisoformat(inputs.data_interval_end)
    return {
        "second": f"{export_datetime:%S}",
        "minute": f"{export_datetime:%M}",
        "hour": f"{export_datetime:%H}",
        "day": f"{export_datetime:%d}",
        "month": f"{export_datetime:%m}",
        "year": f"{export_datetime:%Y}",
        "data_interval_start": inputs.data_interval_start,
        "data_interval_end": inputs.data_interval_end,
        "table": inputs.batch_export_model.name if inputs.batch_export_model is not None else "events",
    }


def get_s3_key_prefix(inputs: S3InsertInputs) -> str:
    template_variables = get_allowed_template_variables(inputs)
    return inputs.prefix.format(**template_variables)


def get_s3_key(inputs: S3InsertInputs, file_number: int = 0) -> str:
    """Return an S3 key given S3InsertInputs."""
    key_prefix = get_s3_key_prefix(inputs)

    try:
        file_extension = FILE_FORMAT_EXTENSIONS[inputs.file_format]
    except KeyError:
        raise UnsupportedFileFormatError(inputs.file_format, "S3")

    base_file_name = f"{inputs.data_interval_start}-{inputs.data_interval_end}"
    # to maintain backwards compatibility with the old file naming scheme
    if inputs.max_file_size_mb is not None:
        base_file_name = f"{base_file_name}-{file_number}"
    if inputs.compression is not None:
        file_name = base_file_name + f".{file_extension}.{COMPRESSION_EXTENSIONS[inputs.compression]}"
    else:
        file_name = base_file_name + f".{file_extension}"

    key = posixpath.join(key_prefix, file_name)

    if posixpath.isabs(key):
        # Keys are relative to root dir, so this would add an extra "/"
        key = posixpath.relpath(key, "/")

    return key


def get_manifest_key(inputs: S3InsertInputs) -> str:
    key_prefix = get_s3_key_prefix(inputs)
    return posixpath.join(key_prefix, f"{inputs.data_interval_start}-{inputs.data_interval_end}_manifest.json")


class InvalidS3Key(Exception):
    """Exception raised when an invalid S3 key is provided."""

    def __init__(self, err):
        super().__init__(f"An invalid S3 key was provided: {err}")


class UploadAlreadyInProgressError(Exception):
    """Exception raised when an S3MultiPartUpload is already in progress."""

    def __init__(self, upload_id):
        super().__init__(f"This upload is already in progress with ID: {upload_id}. Instantiate a new object.")


class NoUploadInProgressError(Exception):
    """Exception raised when there is no S3MultiPartUpload in progress."""

    def __init__(self):
        super().__init__("No multi-part upload is in progress. Call 'create' to start one.")


class IntermittentUploadPartTimeoutError(Exception):
    """Exception raised when an S3 upload part times out.

    This is generally a transient or intermittent error that can be handled by a retry.
    However, it's wrapped by a `botocore.exceptions.ClientError` that generally includes
    non-retryable errors. So, we can re-raise our own exception in those cases.
    """

    def __init__(self, part_number: int):
        super().__init__(f"An intermittent `RequestTimeout` was raised while attempting to upload part {part_number}")


class InvalidS3EndpointError(Exception):
    """Exception raised when an S3 endpoint is invalid."""

    def __init__(self, message: str = "Endpoint URL is invalid."):
        super().__init__(message)


async def upload_manifest_file(inputs: S3InsertInputs, files_uploaded: list[str], manifest_key: str):
    session = aioboto3.Session()
    async with session.client(
        "s3",
        region_name=inputs.region,
        aws_access_key_id=inputs.aws_access_key_id,
        aws_secret_access_key=inputs.aws_secret_access_key,
        endpoint_url=inputs.endpoint_url,
    ) as client:
        await client.put_object(
            Bucket=inputs.bucket_name,
            Key=manifest_key,
            Body=json.dumps({"files": files_uploaded}),
        )


def s3_default_fields() -> list[BatchExportField]:
    """Default fields for an S3 batch export.

    Starting from the common default fields, we add and tweak some fields for
    backwards compatibility.
    """
    batch_export_fields = default_fields()
    batch_export_fields.append({"expression": "elements_chain", "alias": "elements_chain"})
    batch_export_fields.append({"expression": "person_properties", "alias": "person_properties"})
    batch_export_fields.append({"expression": "person_id", "alias": "person_id"})

    # Again, in contrast to other destinations, and for historical reasons, we do not include these fields.
    not_exported_by_default = {"team_id", "set", "set_once"}

    return [field for field in batch_export_fields if field["alias"] not in not_exported_by_default]


@workflow.defn(name="s3-export", failure_exception_types=[workflow.NondeterminismError])
class S3BatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into S3.

    This Workflow is intended to be executed both manually and by a Temporal Schedule.
    When ran by a schedule, `data_interval_end` should be set to `None` so that we will fetch the
    end of the interval from the Temporal search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> S3BatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return S3BatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: S3BatchExportInputs):
        """Workflow implementation to export data to S3 bucket."""
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
        run_id = await workflow.execute_activity(
            start_batch_export_run,
            start_batch_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        insert_inputs = S3InsertInputs(
            bucket_name=inputs.bucket_name,
            region=inputs.region,
            prefix=inputs.prefix,
            team_id=inputs.team_id,
            aws_access_key_id=inputs.aws_access_key_id,
            aws_secret_access_key=inputs.aws_secret_access_key,
            endpoint_url=inputs.endpoint_url or None,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            compression=inputs.compression,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            encryption=inputs.encryption,
            kms_key_id=inputs.kms_key_id,
            file_format=inputs.file_format,
            max_file_size_mb=inputs.max_file_size_mb,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            use_virtual_style_addressing=inputs.use_virtual_style_addressing,
            # TODO: Remove after updating existing batch exports.
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=s3_default_fields(),
        )

        await execute_batch_export_using_internal_stage(
            insert_into_s3_activity_from_stage,
            insert_inputs,
            interval=inputs.interval,
            non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
        )
        return


@activity.defn
async def insert_into_s3_activity_from_stage(inputs: S3InsertInputs) -> RecordsCompleted:
    """Activity to batch export data to a customer's S3.

    This is a new version of the `insert_into_s3_activity` activity that reads data from our internal S3 stage
    instead of ClickHouse.

    It will upload multiple files if the max_file_size_mb is set, otherwise it will upload a single file. File uploads
    are done using multipart upload.

    We could maybe optimize this by simply copying the data from the internal S3 stage to the customer's S3 bucket,
    however, we've tried to keep the activity that writes the data to the internal S3 stage as generic as possible, as
    it will be used by other destinations, not just S3. Our S3 batch exports also support customising the max S3 file
    size, different file formats, compression, etc, which ClickHouse's S3 functions may not support.
    """
    bind_contextvars(
        team_id=inputs.team_id,
        destination="S3",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to S3: %s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        get_s3_key(inputs),
    )

    async with Heartbeater():
        # NOTE: we don't support resuming from heartbeats for this activity for 2 reasons:
        # - resuming from old heartbeats doesn't play nicely with S3 multipart uploads
        # - we don't order the events in the query to ClickHouse
        data_interval_start = (
            dt.datetime.fromisoformat(inputs.data_interval_start) if inputs.data_interval_start else None
        )
        data_interval_end = dt.datetime.fromisoformat(inputs.data_interval_end)

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_S3_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = ProducerFromInternalStage()
        assert inputs.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 60,  # 60MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )

            return 0

        record_batch_schema = pa.schema(
            # NOTE: For some reason, some batches set non-nullable fields as non-nullable, whereas other
            # record batches have them as nullable.
            # Until we figure it out, we set all fields to nullable. There are some fields we know
            # are not nullable, but I'm opting for the more flexible option until we out why schemas differ
            # between batches.
            [field.with_nullable(True) for field in record_batch_schema]
        )

        consumer = ConcurrentS3Consumer(
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            s3_inputs=inputs,
            part_size=settings.BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES,
            max_concurrent_uploads=settings.BATCH_EXPORT_S3_MAX_CONCURRENT_UPLOADS,
        )

        records_completed = await run_consumer_from_stage(
            queue=queue,
            consumer=consumer,
            producer_task=producer_task,
            schema=record_batch_schema,
            file_format=inputs.file_format,
            compression=inputs.compression,
            include_inserted_at=True,
            max_file_size_bytes=inputs.max_file_size_mb * 1024 * 1024 if inputs.max_file_size_mb else 0,
            json_columns=("properties", "person_properties", "set", "set_once"),
        )

        return records_completed


class ConcurrentS3Consumer(ConsumerFromStage):
    """A consumer that uploads chunks of data to S3 concurrently.

    It uses a memory buffer to store the data and upload it in parts. It uses 2 semaphores to limit the number of
    concurrent uploads and the memory buffer.
    """

    UPLOAD_PART_MAX_ATTEMPTS: int = 5
    MAX_RETRY_DELAY: float = 32.0
    INITIAL_RETRY_DELAY: float = 1.0
    EXPONENTIAL_BACKOFF_COEFFICIENT: float = 2.0

    def __init__(
        self,
        data_interval_start: dt.datetime | str | None,
        data_interval_end: dt.datetime | str,
        s3_inputs: S3InsertInputs,
        part_size: int = 50 * 1024 * 1024,  # 50MB parts
        max_concurrent_uploads: int = 5,
    ):
        super().__init__(data_interval_start, data_interval_end)

        self.s3_inputs = s3_inputs
        self.part_size = part_size
        self.max_concurrent_uploads = max_concurrent_uploads
        self.upload_semaphore = asyncio.Semaphore(max_concurrent_uploads)

        self._session = aioboto3.Session()
        self._s3_client: S3Client | None = None  # Shared S3 client
        self._s3_client_ctx: ClientCreatorContext[S3Client] | None = None  # Context manager for cleanup

        # File splitting management
        self.current_file_index = 0
        self.current_file_size = 0

        self.files_uploaded: list[str] = []
        self.current_buffer = bytearray()
        self.pending_uploads: dict[int, asyncio.Task] = {}  # part_number -> Future
        self.completed_parts: dict[int, CompletedPartTypeDef] = {}  # part_number -> part_info
        self.part_counter = 1
        self.upload_id: str | None = None

        self._finalized = False

    async def _get_s3_client(self) -> "S3Client":
        """Get or create the shared S3 client.

        It significantly improves performance to share a single S3 client across all uploads.
        """
        if self._s3_client is None:
            config: dict[str, typing.Any] = {
                "max_pool_connections": self.max_concurrent_uploads
                * 5,  # Increase connection pool, so to ensure we're not limited by this
            }
            if self.s3_inputs.use_virtual_style_addressing:
                config["s3"] = {"addressing_style": "virtual"}
            boto_config = AioConfig(**config)

            try:
                client_ctx = self._session.client(
                    "s3",
                    region_name=self.s3_inputs.region,
                    aws_access_key_id=self.s3_inputs.aws_access_key_id,
                    aws_secret_access_key=self.s3_inputs.aws_secret_access_key,
                    endpoint_url=self.s3_inputs.endpoint_url,
                    config=boto_config,
                )
                self._s3_client = await client_ctx.__aenter__()
                # Store the context manager for proper cleanup
                self._s3_client_ctx = client_ctx
            except ValueError as err:
                if "Invalid endpoint" in str(err):
                    raise InvalidS3EndpointError(str(err)) from err
                raise
        return self._s3_client

    async def finalize_file(self):
        await self._finalize_current_file()
        await self._start_new_file()

    async def consume_chunk(self, data: bytes):
        if self._finalized:
            raise RuntimeError("Consumer already finalized")

        self.current_buffer.extend(data)
        self.current_file_size += len(data)

        # Upload parts when buffer is full
        while len(self.current_buffer) >= self.part_size:
            await self._upload_next_part()
        else:
            # Ensure that we give pending tasks a chance to run.
            await asyncio.sleep(0)

    async def _upload_next_part(self, final: bool = False):
        """Extract a part from buffer and upload it"""
        if not len(self.current_buffer):
            return

        if not self.upload_id:
            await self._initialize_multipart_upload()

        if final:
            self.logger.debug(
                "Uploading final part of file %s with upload id %s", self._get_current_key(), self.upload_id
            )
            # take all the data
            part_data = bytes(self.current_buffer)
        else:
            # Extract part data
            part_data = bytes(self.current_buffer[: self.part_size])
            self.current_buffer = self.current_buffer[self.part_size :]

        part_number = self.part_counter
        self.part_counter += 1

        # Acquire upload semaphore (blocks if too many uploads in flight)
        await self.upload_semaphore.acquire()

        # Create upload task
        upload_task = asyncio.create_task(self._upload_part_with_cleanup(part_data, part_number))
        upload_task.add_done_callback(lambda task: self._on_upload_complete(task, part_number))

        # Track the upload
        self.pending_uploads[part_number] = upload_task

        if final:
            self.current_buffer.clear()

        self.logger.debug(
            "Concurrent uploads running: %s",
            len(self.pending_uploads),
        )

    async def _upload_part_with_cleanup(
        self,
        data: bytes,
        part_number: int,
    ):
        """Upload part and handle cleanup with retry logic.

        Note: This can run concurrently so need to be careful
        """
        # safety check - we should never have a part number without an upload id
        if not self.upload_id:
            raise NoUploadInProgressError()

        try:
            self.logger.debug(
                "Uploading file number %s part %s with upload id %s",
                self.current_file_index,
                part_number,
                self.upload_id,
            )
            current_key = self._get_current_key()
            client = self._s3_client
            assert client is not None, "No S3 client, is multi-part initialized?"

            # Retry logic for upload_part
            response: UploadPartOutputTypeDef | None = None
            attempt = 0

            with ExecutionTimeRecorder(
                "s3_batch_export_upload_part_duration",
                description="Total duration of the upload of a part of a multi-part upload",
                log_message=(
                    "Finished uploading file number %(file_number)d part %(part_number)d"
                    " with upload id '%(upload_id)s' with status '%(status)s'."
                    " File size: %(mb_processed).2f MB, upload time: %(duration_seconds)d"
                    " seconds, speed: %(mb_per_second).2f MB/s"
                ),
                log_attributes={
                    "file_number": self.current_file_index,
                    "upload_id": self.upload_id,
                    "part_number": part_number,
                },
            ) as recorder:
                recorder.add_bytes_processed(len(data))

                while response is None:
                    try:
                        response = await client.upload_part(
                            Bucket=self.s3_inputs.bucket_name,
                            Key=current_key,
                            PartNumber=part_number,
                            UploadId=self.upload_id,
                            Body=data,
                        )

                    except botocore.exceptions.ClientError as err:
                        error_code = err.response.get("Error", {}).get("Code", None)
                        attempt += 1

                        self.logger.warning(
                            "Caught ClientError while uploading file %s part %s: %s (attempt %s/%s)",
                            self.current_file_index,
                            part_number,
                            error_code,
                            attempt,
                            self.UPLOAD_PART_MAX_ATTEMPTS,
                        )

                        if error_code is not None and error_code == "RequestTimeout":
                            if attempt >= self.UPLOAD_PART_MAX_ATTEMPTS:
                                raise IntermittentUploadPartTimeoutError(part_number=part_number) from err

                            retry_delay = min(
                                self.MAX_RETRY_DELAY,
                                self.INITIAL_RETRY_DELAY * (attempt**self.EXPONENTIAL_BACKOFF_COEFFICIENT),
                            )
                            self.logger.warning("Retrying part %s upload in %s seconds", part_number, retry_delay)
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            raise

            part_info: CompletedPartTypeDef = {"ETag": response["ETag"], "PartNumber": part_number}

            # Store completed part info
            self.completed_parts[part_number] = part_info

            return part_info

        except Exception:
            self.logger.exception(
                "Failed to upload file number %s part %s with upload id %s",
                self.current_file_index,
                part_number,
                self.upload_id,
            )
            raise

    def _get_current_key(self) -> str:
        """Generate the key for the current file"""
        return get_s3_key(self.s3_inputs, self.current_file_index)

    async def _start_new_file(self):
        """Start a new file (reset state for file splitting)"""
        self.current_file_index += 1
        self.current_file_size = 0
        self.part_counter = 1
        self.upload_id = None
        self.pending_uploads.clear()
        self.completed_parts.clear()
        self.external_logger.info(
            "Starting multipart upload to '%s' for file number %d", self._get_current_key(), self.current_file_index
        )

    async def _finalize_current_file(self):
        """Finalize the current file before starting a new one"""
        if self.current_file_size == 0:
            return  # Nothing to finalize

        try:
            # Upload any remaining data in buffer
            if len(self.current_buffer) > 0:
                await self._upload_next_part(final=True)

            # Wait for all pending uploads for this file and check for errors
            # TODO - maybe we can improve error handling here
            if self.pending_uploads:
                try:
                    await asyncio.gather(*self.pending_uploads.values())
                except Exception:
                    self.logger.exception("One or more upload parts failed")
                    raise

            # Complete multipart upload if needed
            if self.upload_id:
                await self._complete_multipart_upload()

            self.files_uploaded.append(self._get_current_key())
            self.external_logger.info("Completed multipart upload for file number %d", self.current_file_index)

        except Exception:
            # Cleanup on error
            await self._abort()
            raise

    def _on_upload_complete(self, task: asyncio.Task, part_number: int):
        """Callback called when an upload task completes (success or failure)"""
        self.upload_semaphore.release()

        # Remove from pending uploads immediately
        self.pending_uploads.pop(part_number, None)

        # Handle any exceptions
        if task.exception() is not None:
            # Log the error - the exception will be re-raised when the task is awaited
            self.logger.exception("Upload failed for file number %s part %s", self.current_file_index, part_number)

    async def _initialize_multipart_upload(self):
        """Initialize multipart upload with optimizations for large files"""
        if self.upload_id:
            raise UploadAlreadyInProgressError(self.upload_id)

        optional_kwargs = {}
        if self.s3_inputs.encryption:
            optional_kwargs["ServerSideEncryption"] = self.s3_inputs.encryption
        if self.s3_inputs.kms_key_id:
            optional_kwargs["SSEKMSKeyId"] = self.s3_inputs.kms_key_id

        current_key = self._get_current_key()
        client = await self._get_s3_client()
        response = await client.create_multipart_upload(
            Bucket=self.s3_inputs.bucket_name,
            Key=current_key,
            **optional_kwargs,  # type: ignore
        )
        self.upload_id = response["UploadId"]
        self.logger.debug("Initialized multipart upload for key %s with upload id %s", current_key, self.upload_id)

    async def finalize(self):
        """Finalize upload with proper cleanup"""
        if self._finalized:
            return

        try:
            # Finalize the current/last file
            await self._finalize_current_file()

        except Exception:
            # Cleanup on error
            await self._abort()
            raise
        finally:
            self._finalized = True
            # Final cleanup
            self.current_buffer.clear()
            # Close the shared S3 client
            if self._s3_client is not None and self._s3_client_ctx is not None:
                await self._s3_client_ctx.__aexit__(None, None, None)
                self._s3_client = None
                self._s3_client_ctx = None

        # If using max file size (and therefore potentially expecting more than one file) upload a manifest file
        # containing the list of files.  This is used to check if the export is complete.
        if self.s3_inputs.max_file_size_mb:
            manifest_key = get_manifest_key(self.s3_inputs)
            self.external_logger.info("Uploading manifest file '%s'", manifest_key)
            await upload_manifest_file(self.s3_inputs, self.files_uploaded, manifest_key)
            self.external_logger.info("All uploads completed. Uploaded %d files", len(self.files_uploaded))

    # TODO - maybe we can support upload small files without the need for multipart uploads
    # we just want to ensure we test both versions of the code path
    # async def _single_file_upload(self):
    #     """Handle small files that don't need multipart"""
    #     data = bytes(self.current_buffer)
    #     client = await self._get_s3_client()
    #     await client.put_object(Bucket=self.s3_inputs.bucket_name, Key=self._get_current_key(), Body=data)
    #     self.current_buffer.clear()
    #     self.current_file_size = 0

    async def _complete_multipart_upload(self):
        """Complete multipart upload with parts in order"""
        if not self.upload_id:
            raise NoUploadInProgressError()

        # Sort parts by part number
        sorted_parts = [self.completed_parts[part_num] for part_num in sorted(self.completed_parts.keys())]

        current_key = self._get_current_key()
        client = await self._get_s3_client()
        await client.complete_multipart_upload(
            Bucket=self.s3_inputs.bucket_name,
            Key=current_key,
            UploadId=self.upload_id,
            MultipartUpload={"Parts": sorted_parts},
        )

    async def _abort(self):
        """Abort this S3 multi-part upload."""
        if self.upload_id:
            try:
                client = await self._get_s3_client()
                await client.abort_multipart_upload(
                    Bucket=self.s3_inputs.bucket_name, Key=self._get_current_key(), UploadId=self.upload_id
                )
            except Exception:
                pass  # Best effort cleanup
