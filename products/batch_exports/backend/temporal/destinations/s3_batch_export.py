import asyncio
import collections
import collections.abc
import contextlib
import dataclasses
import datetime as dt
import functools
import io
import json
import operator
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
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import (
    RecordBatchQueue,
    wait_for_schema_or_producer,
)
from products.batch_exports.backend.temporal.utils import handle_non_retryable_errors

NON_RETRYABLE_ERROR_TYPES = (
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
    # Invalid S3 endpoint URL
    "InvalidS3EndpointError",
    # Invalid file_format input
    "UnsupportedFileFormatError",
)

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


class UnsupportedFileFormatError(Exception):
    """Raised when an unsupported file format is requested."""

    def __init__(self, file_format: str):
        super().__init__(f"'{file_format}' is not a supported format for S3 batch exports.")


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
        raise UnsupportedFileFormatError(inputs.file_format)

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
        )
        return


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_s3_activity_from_stage(inputs: S3InsertInputs) -> BatchExportResult:
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

            return BatchExportResult(records_completed=0, bytes_exported=0)

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

        return await run_consumer_from_stage(
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


class Part(typing.NamedTuple):
    number: int
    etag: str

    def as_dict(self) -> dict[str, str | int]:
        return {"PartNumber": self.number, "ETag": self.etag}


class PendingPart(typing.NamedTuple):
    number: int


class S3UploadRetryConfiguration(typing.NamedTuple):
    max_attempts: int = 5
    max_delay: float = 32.0
    initial_delay: float = 1.0
    exponential_backoff_coefficient: float = 2.0


class S3MultiPartUpload:
    """Manage an S3 multipart upload.

    This class is intended to be used as a context manager. Within the context,
    the multipart upload is considered to be in progress, and new parts can be
    uploaded within it.

    Attributes:
        s3_client: S3 client used to make API calls. This does not handle client
            initialization and/or destruction. Callers of this class should care
            for proper management of the provided S3 client.
        bucket_name: Name of the bucket where we are uploading.
        key: Key we are uploading to.
        file_index: The index of the file we are updating.
        encryption: Optional string indicating which encryption to use.
        kms_key_id: Optional KMS key ID for KMS encryption.
        retry: Retry configuration for upload part calls.
    """

    def __init__(
        self,
        s3_client: "S3Client",
        bucket_name: str,
        key: str,
        file_index: int,
        encryption: str | None,
        kms_key_id: str | None,
        retry: S3UploadRetryConfiguration | None = None,
    ) -> None:
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.key = key
        self.encryption = encryption
        self.kms_key_id = kms_key_id
        self.file_index = file_index
        self.retry = retry or S3UploadRetryConfiguration()

        self.logger = LOGGER.bind(bucket_name=bucket_name, key=key)

        self._upload_id: str | None = None
        self._parts: set[Part] = set()
        self._pending_uploads: set[asyncio.Task[Part]] = set()
        self._task_group: asyncio.TaskGroup | None = None

    @classmethod
    def from_inputs(
        cls,
        inputs: S3InsertInputs,
        s3_client: "S3Client",
        file_index: int,
        retry: S3UploadRetryConfiguration | None = None,
    ) -> typing.Self:
        """Initialize this with `S3InsertInputs` and required arguments.

        Arguments:
            inputs: Inputs to the S3 insert activity.
            s3_client: Passed along to initialization method.
            file_index: File index used to compute multipart upload key.
            retry: Passed along to initialization method.
        """
        key = get_s3_key(inputs, file_index)
        return cls(
            s3_client=s3_client,
            bucket_name=inputs.bucket_name,
            key=key,
            file_index=file_index,
            encryption=inputs.encryption,
            kms_key_id=inputs.kms_key_id,
            retry=retry,
        )

    @property
    def upload_id(self) -> str:
        """Return upload ID for in progress multipart upload."""
        if not self._upload_id:
            raise NoUploadInProgressError()

        return self._upload_id

    @upload_id.setter
    def upload_id(self, value: str | None) -> None:
        """Set or unset upload id from logger when setting attribute."""
        if value:
            self.logger = self.logger.bind(upload_id=value)
        else:
            self.logger.unbind("upload_id")
        self._upload_id = value

    @property
    def task_group(self) -> asyncio.TaskGroup:
        """Return task group used for in progress multipart upload."""
        if not self._task_group:
            raise NoUploadInProgressError()

        return self._task_group

    @property
    def total_parts(self) -> int:
        """Return the amount of parts uploaded and in progress."""
        return len(self._parts) + len(self._pending_uploads)

    def is_upload_in_progress(self) -> bool:
        return self._upload_id is not None

    async def start(self) -> str:
        """Start this S3MultiPartUpload."""
        if self.is_upload_in_progress() is True:
            raise UploadAlreadyInProgressError(self.upload_id)

        self.logger.info("Starting multipart upload")

        optional_kwargs = {}
        if self.encryption:
            optional_kwargs["ServerSideEncryption"] = self.encryption
        if self.kms_key_id:
            optional_kwargs["SSEKMSKeyId"] = self.kms_key_id

        try:
            multipart_response = await self.s3_client.create_multipart_upload(
                Bucket=self.bucket_name,
                Key=self.key,
                **optional_kwargs,  # type: ignore
            )
        except Exception:
            self.logger.exception("Failed to start multipart upload")
            raise

        upload_id: str = multipart_response["UploadId"]
        self.upload_id = upload_id

        self.logger.info("Started multipart upload")

        return upload_id

    async def complete(self) -> str:
        self.logger.info("Completing multipart upload")

        sorted_parts = [p.as_dict() for p in sorted(self._parts, key=operator.attrgetter("number"))]

        response = await self.s3_client.complete_multipart_upload(
            Bucket=self.bucket_name,
            Key=self.key,
            UploadId=self.upload_id,
            MultipartUpload={"Parts": sorted_parts},  # type: ignore
        )

        self.logger.info("Completed multipart upload")

        return response["Key"]

    async def abort(self) -> None:
        """Attempt to abort this multipart upload."""
        self.logger.info("Aborting multipart upload")

        try:
            _ = await self.s3_client.abort_multipart_upload(
                Bucket=self.bucket_name,
                Key=self.key,
                UploadId=self.upload_id,
            )
        except Exception:
            self.logger.exception("Ignoring error that occurred when aborting multipart upload")

        self._parts.clear()

        self.logger.info("Aborted multipart upload")

    def upload_next_part(self, body: bytes | bytearray | memoryview) -> asyncio.Task[Part]:
        """Start a task for next upload part with body."""
        part_number = self.total_parts + 1

        upload_task = self.task_group.create_task(self.upload_part(body, part_number))
        upload_task.add_done_callback(self._on_upload_done)
        self._pending_uploads.add(upload_task)

        return upload_task

    def _on_upload_done(self, task: asyncio.Task[Part]) -> None:
        """Callback attached to each `upload_part` task.

        We don't handle exceptions as the task group will handle them.
        """
        self._pending_uploads.remove(task)

        if not task.exception():
            self._parts.add(task.result())

    async def upload_part(
        self,
        body: bytes | bytearray | memoryview,
        part_number: int,
    ) -> Part:
        """Upload part and handle cleanup with retry logic.

        Note: This can run concurrently so need to be careful
        """
        try:
            self.logger.info(
                "Uploading file number %s part %s with upload id %s",
                self.file_index,
                part_number,
                self.upload_id,
            )
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
                    "file_number": self.file_index,
                    "upload_id": self.upload_id,
                    "part_number": part_number,
                },
            ) as recorder:
                recorder.add_bytes_processed(len(body))

                while response is None:
                    try:
                        response = await self.s3_client.upload_part(
                            Bucket=self.bucket_name,
                            Key=self.key,
                            PartNumber=part_number,
                            UploadId=self.upload_id,
                            Body=io.BytesIO(body),
                        )

                    except botocore.exceptions.ClientError as err:
                        error_code = err.response.get("Error", {}).get("Code", None)
                        attempt += 1

                        self.logger.warning(
                            "Caught ClientError while uploading file %d part %d: '%s' (attempt %d/%d)",
                            self.file_index,
                            part_number,
                            error_code,
                            attempt,
                            self.retry.max_attempts,
                        )

                        if error_code is not None and error_code == "RequestTimeout":
                            if attempt >= self.retry.max_attempts:
                                raise IntermittentUploadPartTimeoutError(part_number=part_number) from err

                            retry_delay = min(
                                self.retry.max_delay,
                                self.retry.initial_delay * (attempt**self.retry.exponential_backoff_coefficient),
                            )
                            self.logger.warning("Retrying part %d upload in %d seconds", part_number, retry_delay)
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            raise

            return Part(number=part_number, etag=response["ETag"])

        except Exception:
            self.logger.exception(
                "Failed to upload file number %s part %s with upload id %s",
                self.file_index,
                part_number,
                self.upload_id,
            )
            raise

    @contextlib.asynccontextmanager
    async def run(self) -> collections.abc.AsyncIterator[typing.Self]:
        """Run a multipart upload within this context.

        The multipart upload is started on entering. Together with initializing
        an `asyncio.TaskGroup` which will keep track of all uploads. This
        ensures any pending uploads are canceled when one fails, as a multipart
        upload cannot be considered successful if even one part fails.

        In the event anything is raised within the context, this attempts to
        abort the multipart upload before re-raising the exception.
        """

        await self.start()

        try:
            async with asyncio.TaskGroup() as tg:
                self._task_group = tg

                yield self
        except Exception:
            await self.abort()
            raise
        else:
            await self.complete()
        finally:
            self._upload_id = None
            self._task_group = None


class BytesQueue(asyncio.Queue):
    """Subclass of asyncio.Queue limited by number of bytes."""

    def __init__(self, max_size_bytes: int = 0) -> None:
        super().__init__(maxsize=max_size_bytes)
        self._bytes_size = 0
        # This is set by `asyncio.Queue.__init__` calling `_init`
        self._queue: collections.deque
        self._finished: asyncio.Event

    def _put(self, item: bytes | bytearray | memoryview | None) -> None:
        """Override parent `_put` to keep track of bytes."""
        if item:
            self._bytes_size += len(item)

        self._queue.append(item)

    def bytes_done(self, bytes: int) -> None:
        """Indicate a certain amount of bytes has been processed."""
        if self._bytes_size <= 0:
            raise ValueError("bytes_done() called with too many bytes")

        self._bytes_size -= bytes

        if self._bytes_size == 0:
            self._finished.set()

    def qsize(self) -> int:
        """Size in bytes of record batches in the queue.

        This is used to determine when the queue is full, so it returns the
        number of bytes.
        """
        return self._bytes_size


S3MultipartUploadTask = asyncio.Task[None]


class ActiveS3MultipartUpload(typing.NamedTuple):
    """Tuple keeping track of an active upload and queue associated with it."""

    task: S3MultipartUploadTask
    queue: BytesQueue


class ConcurrentS3Consumer(ConsumerFromStage):
    """A consumer that uploads chunks of data to S3 concurrently.

    It uses a memory buffer to store the data and upload it in parts.
    """

    def __init__(
        self,
        data_interval_start: dt.datetime | str | None,
        data_interval_end: dt.datetime | str,
        s3_inputs: S3InsertInputs,
        part_size: int = 50 * 1024 * 1024,  # 50MB parts
        max_concurrent_uploads: int = 5,
    ) -> None:
        super().__init__(data_interval_start, data_interval_end)

        self.s3_inputs = s3_inputs
        self.part_size = part_size
        self.max_concurrent_uploads = max_concurrent_uploads
        self.upload_semaphore = asyncio.Semaphore(max_concurrent_uploads)
        self.current_file_index = 0
        self.files_uploaded: list[str] = []

        self._pending_multipart_uploads: dict[int, ActiveS3MultipartUpload] = {}

        # Internal S3 client management
        self._session = aioboto3.Session()
        self._s3_client: S3Client | None = None  # Shared S3 client
        self._s3_client_ctx: ClientCreatorContext[S3Client] | None = None  # Context manager for cleanup

        self._finalized = False

    async def consume_chunk(self, data: bytes) -> None:
        """Queue-up a chunk of data to be uploaded to S3.

        If a multipart upload is not in progress for the current file, this
        creates one.
        """
        if self._finalized:
            raise RuntimeError("Consumer already finalized")

        if self.current_file_index not in self._pending_multipart_uploads:
            queue = BytesQueue(self.max_concurrent_uploads * self.part_size)
            task = asyncio.create_task(self.run_multipart_upload(queue))
            task.add_done_callback(self._on_multipart_upload_done)
            self._pending_multipart_uploads[self.current_file_index] = ActiveS3MultipartUpload(task=task, queue=queue)

        task, queue = self._pending_multipart_uploads[self.current_file_index]

        await queue.put(data)

    async def run_multipart_upload(self, queue: BytesQueue) -> None:
        """Run a multipart upload to upload bytes from queue."""
        file_index = self.current_file_index

        s3_client = await self._get_s3_client()
        multipart_upload = S3MultiPartUpload.from_inputs(
            self.s3_inputs, s3_client=s3_client, file_index=self.current_file_index
        )

        async with multipart_upload.run() as multipart_upload:
            self.external_logger.info(
                "Starting multipart upload to '%s' for file number %d", multipart_upload.key, file_index
            )

            buffer = bytearray()
            is_last = False

            while not is_last:
                try:
                    buffer += await queue.get()
                except TypeError:
                    if not buffer:
                        break

                    part_body = memoryview(buffer)
                    is_last = True
                else:
                    if len(buffer) < self.part_size:
                        continue

                    part_body, buffer = memoryview(buffer)[: self.part_size], buffer[self.part_size :]

                await self.upload_semaphore.acquire()

                part_body_size = len(part_body)
                done_callback = functools.partial(self._on_upload_part_done, queue=queue, part_body_size=part_body_size)

                upload_task = multipart_upload.upload_next_part(part_body)
                upload_task.add_done_callback(done_callback)

        self.external_logger.info("Completed multipart upload for file number %d", file_index)
        self.files_uploaded.append(multipart_upload.key)

    def _on_upload_part_done(self, _: asyncio.Task[Part], queue: BytesQueue, part_body_size: int) -> None:
        """Callback to release global semaphore and signal upload's queue."""
        self.upload_semaphore.release()
        queue.bytes_done(part_body_size)

    def _on_multipart_upload_done(self, task: asyncio.Task[None]) -> None:
        """Callback to raise early in case multipart upload fails."""
        exc = task.exception()
        if exc is None:
            return
        raise exc

    async def finalize_file(self) -> None:
        """Call to mark the end of the current file.

        All chunks consumed afterwards will be uploaded to a new file.
        """
        await self._finalize_current_file()
        self._start_new_file()

    async def _finalize_current_file(self) -> None:
        """Finalize the current file by signaling its associated upload."""
        _, queue = self._pending_multipart_uploads[self.current_file_index]
        await queue.put(None)

    def _start_new_file(self) -> None:
        """Increment file index to start a new file upload on the next chunk."""
        self.current_file_index += 1

    async def finalize(self) -> None:
        """Finalize the consumer.

        This involves:
        1. Awaiting any pending uploads.
        2. Closing the S3 client.
        3. Uploading a manifest file (if required).
        """
        if self._finalized:
            return

        if self.current_file_index in self._pending_multipart_uploads:
            await self._finalize_current_file()

        try:
            await asyncio.wait([active.task for active in self._pending_multipart_uploads.values()])
        finally:
            self._finalized = True

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

    # TODO - maybe we can support upload small files without the need for multipart uploads
    # we just want to ensure we test both versions of the code path
    # async def _single_file_upload(self):
    #     """Handle small files that don't need multipart"""
    #     data = bytes(self.current_buffer)
    #     client = await self._get_s3_client()
    #     await client.put_object(Bucket=self.s3_inputs.bucket_name, Key=self._get_current_key(), Body=data)
    #     self.current_buffer.clear()
    #     self.current_file_size = 0


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
