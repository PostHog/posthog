import asyncio
import collections.abc
import contextlib
import dataclasses
import datetime as dt
import io
import json
import operator
import posixpath
import typing

import aioboto3
import botocore.exceptions
import pyarrow as pa
from django.conf import settings
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportInsertInputs,
    S3BatchExportInputs,
)
from posthog.temporal.batch_exports.batch_exports import (
    FinishBatchExportRunInputs,
    RecordsCompleted,
    StartBatchExportRunInputs,
    default_fields,
    execute_batch_export_insert_activity,
    get_data_interval,
    start_batch_export_run,
)
from posthog.temporal.batch_exports.heartbeat import (
    BatchExportRangeHeartbeatDetails,
    DateRange,
    HeartbeatParseError,
    should_resume_from_activity_heartbeat,
)
from posthog.temporal.batch_exports.spmc import (
    Consumer,
    Producer,
    RecordBatchQueue,
    resolve_batch_exports_model,
    run_consumer,
    wait_for_schema_or_producer,
)
from posthog.temporal.batch_exports.temporary_file import (
    BatchExportTemporaryFile,
    UnsupportedFileFormatError,
    WriterFormat,
)
from posthog.temporal.batch_exports.utils import set_status_to_running_task
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import (
    bind_temporal_worker_logger,
    get_internal_logger,
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
    "ztsd": "zst",
    "lz4": "lz4",
}


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


Part = dict[str, str | int]


class S3MultiPartUploadState(typing.NamedTuple):
    upload_id: str
    parts: list[Part]


class S3MultiPartUpload:
    """An S3 multi-part upload.

    The purpose of this class is to track the progress of an S3 multi-par upload
    during a batch export activity that may span multiple attempts.

    Attributes:
        region_name: The name of the region where the bucket we are batch exporting to is located.
        bucket_name: The name of the bucket where we are batch exporting to.
        key: The key for the object we are batch exporting.
        encryption: An optional encryption option, like 'aws:kms'.
        kms_key_id: If using 'aws:kms' encryption, the KMS key ID.
        aws_access_key_id: The AWS access key ID used to connect to the bucket.
        aws_secret_access_key: The AWS secret access key used to connect to the bucket.
    """

    def __init__(
        self,
        region_name: str,
        bucket_name: str,
        key: str,
        encryption: str | None,
        kms_key_id: str | None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        endpoint_url: str | None = None,
    ):
        self._session = aioboto3.Session()
        self.region_name = region_name
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.endpoint_url = endpoint_url
        self.bucket_name = bucket_name
        self.key = key
        self.encryption = encryption
        self.kms_key_id = kms_key_id
        self.upload_id: str | None = None
        self.parts: list[Part] = []
        self.pending_parts: list[Part] = []

        if self.endpoint_url == "":
            raise InvalidS3EndpointError("Endpoint URL is empty.")

        self.logger = get_internal_logger()

    def to_state(self) -> S3MultiPartUploadState:
        """Produce state tuple that can be used to resume this S3MultiPartUpload."""
        # The second predicate is trivial but required by type-checking.
        if self.is_upload_in_progress() is False or self.upload_id is None:
            raise NoUploadInProgressError()

        return S3MultiPartUploadState(self.upload_id, self.parts)

    @property
    def part_number(self):
        """Return the current part number."""
        return len(self.parts) + len(self.pending_parts)

    def is_upload_in_progress(self) -> bool:
        """Whether this S3MultiPartUpload is in progress or not."""
        if self.upload_id is None:
            return False
        return True

    @contextlib.asynccontextmanager
    async def s3_client(self):
        """Asynchronously yield an S3 client."""

        try:
            async with self._session.client(
                "s3",
                region_name=self.region_name,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                endpoint_url=self.endpoint_url,
            ) as client:
                yield client
        except ValueError as err:
            if "Invalid endpoint" in str(err):
                raise InvalidS3EndpointError(str(err)) from err
            raise

    async def start(self) -> str:
        """Start this S3MultiPartUpload."""
        if self.is_upload_in_progress() is True:
            raise UploadAlreadyInProgressError(self.upload_id)

        optional_kwargs = {}
        if self.encryption:
            optional_kwargs["ServerSideEncryption"] = self.encryption
        if self.kms_key_id:
            optional_kwargs["SSEKMSKeyId"] = self.kms_key_id

        async with self.s3_client() as s3_client:
            multipart_response = await s3_client.create_multipart_upload(
                Bucket=self.bucket_name,
                Key=self.key,
                **optional_kwargs,
            )

        upload_id: str = multipart_response["UploadId"]
        self.upload_id = upload_id
        await self.logger.adebug("Started multipart upload for key %s with upload id %s", self.key, upload_id)
        return upload_id

    async def continue_from_state(self, state: S3MultiPartUploadState):
        """Continue this S3MultiPartUpload from a previous state.

        This method is intended to be used with the state found in an Activity heartbeat.
        """
        self.upload_id = state.upload_id
        self.parts = state.parts
        await self.logger.adebug("Resuming multipart upload for key %s with upload id %s", self.key, self.upload_id)
        return self.upload_id

    async def complete(self) -> str | None:
        if self.is_upload_in_progress() is False:
            raise NoUploadInProgressError()

        sorted_parts = sorted(self.parts, key=operator.itemgetter("PartNumber"))
        async with self.s3_client() as s3_client:
            response = await s3_client.complete_multipart_upload(
                Bucket=self.bucket_name,
                Key=self.key,
                UploadId=self.upload_id,
                MultipartUpload={"Parts": sorted_parts},
            )

        self.upload_id = None
        self.parts = []

        return response.get("Key")

    async def abort(self):
        """Abort this S3 multi-part upload."""
        if self.is_upload_in_progress() is False:
            raise NoUploadInProgressError()

        async with self.s3_client() as s3_client:
            await s3_client.abort_multipart_upload(
                Bucket=self.bucket_name,
                Key=self.key,
                UploadId=self.upload_id,
            )

        self.upload_id = None
        self.parts = []

    async def upload_part(
        self,
        body: BatchExportTemporaryFile,
        rewind: bool = True,
        max_attempts: int = 5,
        initial_retry_delay: float | int = 2,
        max_retry_delay: float | int = 32,
        exponential_backoff_coefficient: int = 2,
    ):
        """Upload a part of this multi-part upload."""
        next_part_number = self.part_number + 1
        part = {"PartNumber": next_part_number, "ETag": ""}
        self.pending_parts.append(part)

        if rewind is True:
            body.rewind()

        # aiohttp is not duck-type friendly and requires a io.IOBase
        # We comply with the file-like interface of io.IOBase.
        # So we tell mypy to be nice with us.
        reader = io.BufferedReader(body)  # type: ignore

        try:
            etag = await self.upload_part_retryable(
                reader,
                next_part_number,
                max_attempts=max_attempts,
                initial_retry_delay=initial_retry_delay,
                max_retry_delay=max_retry_delay,
                exponential_backoff_coefficient=exponential_backoff_coefficient,
            )
        except Exception:
            raise

        finally:
            reader.detach()  # BufferedReader closes the file otherwise.

        self.pending_parts.pop(self.pending_parts.index(part))
        part["ETag"] = etag
        self.parts.append(part)

    async def upload_part_retryable(
        self,
        reader: io.BufferedReader,
        next_part_number: int,
        max_attempts: int = 5,
        initial_retry_delay: float | int = 2,
        max_retry_delay: float | int = 32,
        exponential_backoff_coefficient: int = 2,
    ) -> str:
        """Attempt to upload a part for this multi-part upload retrying on transient errors."""
        response: dict[str, str] | None = None
        attempt = 0

        async with self.s3_client() as s3_client:
            while response is None:
                try:
                    response = await s3_client.upload_part(
                        Bucket=self.bucket_name,
                        Key=self.key,
                        PartNumber=next_part_number,
                        UploadId=self.upload_id,
                        Body=reader,
                    )

                except botocore.exceptions.ClientError as err:
                    error_code = err.response.get("Error", {}).get("Code", None)
                    attempt += 1

                    await self.logger.ainfo(
                        "Caught ClientError while uploading part %s: %s", next_part_number, error_code
                    )

                    if error_code is not None and error_code == "RequestTimeout":
                        if attempt >= max_attempts:
                            raise IntermittentUploadPartTimeoutError(part_number=next_part_number) from err

                        await asyncio.sleep(
                            min(max_retry_delay, initial_retry_delay * (attempt**exponential_backoff_coefficient))
                        )

                        continue
                    else:
                        raise

        return response["ETag"]

    async def __aenter__(self):
        """Asynchronous context manager protocol enter."""
        if not self.is_upload_in_progress():
            await self.start()

        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> bool:
        """Asynchronous context manager protocol exit.

        We re-raise any exceptions captured.
        """
        return False


@dataclasses.dataclass
class S3HeartbeatDetails(BatchExportRangeHeartbeatDetails):
    """This tuple allows us to enforce a schema on the Heartbeat details.

    Attributes:
        upload_state: State to continue a S3MultiPartUpload when activity execution resumes.
        files_uploaded: The number of files we have uploaded so far
            (we can upload several multi-part uploads in a single activity)
    """

    upload_state: S3MultiPartUploadState | None = None
    files_uploaded: int = 0

    @classmethod
    def deserialize_details(cls, details: collections.abc.Sequence[typing.Any]) -> dict[str, typing.Any]:
        """Attempt to initialize HeartbeatDetails from an activity's details."""
        upload_state = None
        files_uploaded = 0
        remaining = super().deserialize_details(details)

        if len(remaining["_remaining"]) == 0:
            return {"upload_state": upload_state, "files_uploaded": files_uploaded, **remaining}

        first_detail = remaining["_remaining"][0]
        remaining["_remaining"] = remaining["_remaining"][1:]

        if first_detail is None:
            upload_state = None
        else:
            try:
                upload_state = S3MultiPartUploadState(*first_detail)
            except (TypeError, ValueError) as e:
                raise HeartbeatParseError("upload_state") from e

        second_detail = remaining["_remaining"][0]
        remaining["_remaining"] = remaining["_remaining"][1:]

        try:
            files_uploaded = int(second_detail)
        except (TypeError, ValueError) as e:
            raise HeartbeatParseError("files_uploaded") from e

        return {"upload_state": upload_state, "files_uploaded": files_uploaded, **remaining}

    def serialize_details(self) -> tuple[typing.Any, ...]:
        """Attempt to initialize HeartbeatDetails from an activity's details."""
        serialized_parent_details = super().serialize_details()
        return (*serialized_parent_details[:-1], self.upload_state, self.files_uploaded, self._remaining)

    def append_upload_state(self, upload_state: S3MultiPartUploadState):
        if self.upload_state is None:
            self.upload_state = upload_state

        current_parts = {part["PartNumber"] for part in self.upload_state.parts}
        for part in upload_state.parts:
            if part["PartNumber"] not in current_parts:
                self.upload_state.parts.append(part)

    def mark_file_upload_as_complete(self):
        self.files_uploaded += 1
        self.upload_state = None


class S3Consumer(Consumer):
    def __init__(
        self,
        heartbeater: Heartbeater,
        heartbeat_details: S3HeartbeatDetails,
        data_interval_start: dt.datetime | str | None,
        data_interval_end: dt.datetime | str,
        writer_format: WriterFormat,
        s3_inputs: S3InsertInputs,
    ):
        super().__init__(
            heartbeater=heartbeater,
            heartbeat_details=heartbeat_details,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            writer_format=writer_format,
        )
        self.heartbeat_details: S3HeartbeatDetails = heartbeat_details
        self.s3_upload: S3MultiPartUpload | None = None
        self.s3_inputs = s3_inputs
        self.file_number = 0
        self.files_uploaded: list[str] = []

    async def flush(
        self,
        batch_export_file: BatchExportTemporaryFile,
        records_since_last_flush: int,
        bytes_since_last_flush: int,
        flush_counter: int,
        last_date_range: DateRange,
        is_last: bool,
        error: Exception | None,
    ):
        if error is not None:
            if not self.s3_upload:
                return
            await self.logger.adebug("Error while writing part %d", self.s3_upload.part_number + 1, exc_info=error)
            await self.logger.awarning(
                "An error was detected while writing part %d. Partial part will not be uploaded in case it can be retried.",
                self.s3_upload.part_number + 1,
            )
            return

        if self.s3_upload is None:
            self.s3_upload = initialize_upload(self.s3_inputs, self.file_number)

        async with self.s3_upload as s3_upload:
            await self.logger.adebug(
                "Uploading file number %s part %s with upload id %s containing %s records with size %s bytes",
                self.file_number,
                s3_upload.part_number + 1,
                s3_upload.upload_id,
                records_since_last_flush,
                bytes_since_last_flush,
            )
            await s3_upload.upload_part(batch_export_file)

            self.rows_exported_counter.add(records_since_last_flush)
            self.bytes_exported_counter.add(bytes_since_last_flush)

            if is_last:
                await self.logger.adebug(
                    "Completing multipart upload %s for file number %s", s3_upload.upload_id, self.file_number
                )
                await s3_upload.complete()

        if is_last:
            self.files_uploaded.append(s3_upload.key)
            self.s3_upload = None
            self.heartbeat_details.mark_file_upload_as_complete()
            self.file_number += 1
        else:
            self.heartbeat_details.append_upload_state(self.s3_upload.to_state())

        self.heartbeat_details.records_completed += records_since_last_flush
        self.heartbeat_details.track_done_range(last_date_range, self.data_interval_start)

    async def close(self):
        if self.s3_upload is not None:
            await self.logger.adebug(
                "Completing multipart upload %s for file number %s", self.s3_upload.upload_id, self.file_number
            )
            await self.s3_upload.complete()
            self.heartbeat_details.mark_file_upload_as_complete()
            self.files_uploaded.append(self.s3_upload.key)

        # If using max file size (and therefore potentially expecting more than one file) upload a manifest file
        # containing the list of files.  This is used to check if the export is complete.
        if self.s3_inputs.max_file_size_mb:
            manifest_key = get_manifest_key(self.s3_inputs)
            await self.logger.ainfo("Uploading manifest file %s", manifest_key)
            await upload_manifest_file(self.s3_inputs, self.files_uploaded, manifest_key)


async def initialize_and_resume_multipart_upload(
    inputs: S3InsertInputs,
) -> tuple[S3MultiPartUpload, S3HeartbeatDetails]:
    """Initialize a S3MultiPartUpload and resume it from a hearbeat state if available."""
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="S3")

    _, details = await should_resume_from_activity_heartbeat(activity, S3HeartbeatDetails)
    if details is None:
        details = S3HeartbeatDetails()

    files_uploaded = details.files_uploaded or 0
    file_number = files_uploaded

    s3_upload = initialize_upload(inputs, file_number)

    if details.upload_state:
        await s3_upload.continue_from_state(details.upload_state)

        if inputs.compression == "brotli":
            # Even if we receive details we cannot resume a brotli compressed upload as
            # we have lost the compressor state.
            interval_start = inputs.data_interval_start

            await logger.ainfo(
                f"Export will start from the beginning as we are using brotli compression: %s",
                interval_start,
            )
            await s3_upload.abort()

    return s3_upload, details


def initialize_upload(inputs: S3InsertInputs, file_number: int) -> S3MultiPartUpload:
    """Initialize a S3MultiPartUpload."""

    try:
        key = get_s3_key(inputs, file_number)
    except Exception as e:
        raise InvalidS3Key(e) from e

    return S3MultiPartUpload(
        bucket_name=inputs.bucket_name,
        key=key,
        encryption=inputs.encryption,
        kms_key_id=inputs.kms_key_id,
        region_name=inputs.region,
        aws_access_key_id=inputs.aws_access_key_id,
        aws_secret_access_key=inputs.aws_secret_access_key,
        endpoint_url=inputs.endpoint_url or None,
    )


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


@activity.defn
async def insert_into_s3_activity(inputs: S3InsertInputs) -> RecordsCompleted:
    """Activity to batch export data from PostHog's ClickHouse to S3.

    It will upload multiple files if the max_file_size_mb is set, otherwise it
    will upload a single file. File uploads are done using multipart upload.

    TODO: this implementation currently tries to export as one run, but it could
    be a very big date range and time consuming, better to split into multiple
    runs, timing out after say 30 seconds or something and upload multiple
    files.
    """
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="S3")
    await logger.ainfo(
        "Batch exporting range %s - %s to S3: %s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        get_s3_key(inputs),
    )

    async with (
        Heartbeater() as heartbeater,
        set_status_to_running_task(run_id=inputs.run_id, logger=logger),
    ):
        details = S3HeartbeatDetails()
        done_ranges: list[DateRange] = details.done_ranges

        _, record_batch_model, model_name, fields, filters, extra_query_parameters = resolve_batch_exports_model(
            inputs.team_id, inputs.is_backfill, inputs.batch_export_model, inputs.batch_export_schema
        )
        data_interval_start = (
            dt.datetime.fromisoformat(inputs.data_interval_start) if inputs.data_interval_start else None
        )
        data_interval_end = dt.datetime.fromisoformat(inputs.data_interval_end)
        full_range = (data_interval_start, data_interval_end)

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_S3_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = Producer(record_batch_model)
        producer_task = await producer.start(
            queue=queue,
            model_name=model_name,
            is_backfill=inputs.get_is_backfill(),
            backfill_details=inputs.backfill_details,
            team_id=inputs.team_id,
            full_range=full_range,
            done_ranges=done_ranges,
            fields=fields,
            filters=filters,
            destination_default_fields=s3_default_fields(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            extra_query_parameters=extra_query_parameters,
            max_record_batch_size_bytes=1024 * 1024 * 10,  # 10MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            return details.records_completed

        record_batch_schema = pa.schema(
            # NOTE: For some reason, some batches set non-nullable fields as non-nullable, whereas other
            # record batches have them as nullable.
            # Until we figure it out, we set all fields to nullable. There are some fields we know
            # are not nullable, but I'm opting for the more flexible option until we out why schemas differ
            # between batches.
            [field.with_nullable(True) for field in record_batch_schema]
        )

        consumer = S3Consumer(
            heartbeater=heartbeater,
            heartbeat_details=details,
            data_interval_end=data_interval_end,
            data_interval_start=data_interval_start,
            writer_format=WriterFormat.from_str(inputs.file_format, "S3"),
            s3_inputs=inputs,
        )
        _ = await run_consumer(
            consumer=consumer,
            queue=queue,
            producer_task=producer_task,
            schema=record_batch_schema,
            max_bytes=settings.BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES,
            include_inserted_at=True,
            writer_file_kwargs={"compression": inputs.compression},
            max_file_size_bytes=inputs.max_file_size_mb * 1024 * 1024 if inputs.max_file_size_mb else 0,
        )

        return details.records_completed


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

        finish_inputs = FinishBatchExportRunInputs(
            id=run_id,
            batch_export_id=inputs.batch_export_id,
            status=BatchExportRun.Status.COMPLETED,
            team_id=inputs.team_id,
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
            # TODO: Remove after updating existing batch exports.
            batch_export_schema=inputs.batch_export_schema,
        )

        await execute_batch_export_insert_activity(
            insert_into_s3_activity,
            insert_inputs,
            interval=inputs.interval,
            non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
            finish_inputs=finish_inputs,
        )
