import asyncio
import contextlib
import datetime as dt
import io
import json
import posixpath
import typing
from dataclasses import dataclass

import aioboto3
from django.conf import settings
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import BatchExportField, BatchExportSchema, S3BatchExportInputs
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.batch_exports.batch_exports import (
    BatchExportTemporaryFile,
    CreateBatchExportRunInputs,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    default_fields,
    execute_batch_export_insert_activity,
    get_data_interval,
    get_rows_count,
    iter_records,
)
from posthog.temporal.batch_exports.clickhouse import get_client
from posthog.temporal.batch_exports.metrics import (
    get_bytes_exported_metric,
    get_rows_exported_metric,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger


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
        "table": "events",
    }


def get_s3_key(inputs) -> str:
    """Return an S3 key given S3InsertInputs."""
    template_variables = get_allowed_template_variables(inputs)
    key_prefix = inputs.prefix.format(**template_variables)

    base_file_name = f"{inputs.data_interval_start}-{inputs.data_interval_end}"
    match inputs.compression:
        case "gzip":
            file_name = base_file_name + ".jsonl.gz"
        case "brotli":
            file_name = base_file_name + ".jsonl.br"
        case _:
            file_name = base_file_name + ".jsonl"

    key = posixpath.join(key_prefix, file_name)

    if posixpath.isabs(key):
        # Keys are relative to root dir, so this would add an extra "/"
        key = posixpath.relpath(key, "/")

    return key


class UploadAlreadyInProgressError(Exception):
    """Exception raised when an S3MultiPartUpload is already in progress."""

    def __init__(self, upload_id):
        super().__init__(f"This upload is already in progress with ID: {upload_id}. Instantiate a new object.")


class NoUploadInProgressError(Exception):
    """Exception raised when there is no S3MultiPartUpload in progress."""

    def __init__(self):
        super().__init__("No multi-part upload is in progress. Call 'create' to start one.")


class S3MultiPartUploadState(typing.NamedTuple):
    upload_id: str
    parts: list[dict[str, str | int]]


Part = dict[str, str | int]


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
    ):
        self._session = aioboto3.Session()
        self.region_name = region_name
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.bucket_name = bucket_name
        self.key = key
        self.encryption = encryption
        self.kms_key_id = kms_key_id
        self.upload_id: str | None = None
        self.parts: list[Part] = []

    def to_state(self) -> S3MultiPartUploadState:
        """Produce state tuple that can be used to resume this S3MultiPartUpload."""
        # The second predicate is trivial but required by type-checking.
        if self.is_upload_in_progress() is False or self.upload_id is None:
            raise NoUploadInProgressError()

        return S3MultiPartUploadState(self.upload_id, self.parts)

    @property
    def part_number(self):
        """Return the current part number."""
        return len(self.parts)

    def is_upload_in_progress(self) -> bool:
        """Whether this S3MultiPartUpload is in progress or not."""
        if self.upload_id is None:
            return False
        return True

    @contextlib.asynccontextmanager
    async def s3_client(self):
        """Asynchronously yield an S3 client."""
        async with self._session.client(
            "s3",
            region_name=self.region_name,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        ) as client:
            yield client

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

        return upload_id

    def continue_from_state(self, state: S3MultiPartUploadState):
        """Continue this S3MultiPartUpload from a previous state.

        This method is intended to be used with the state found in an Activity heartbeat.
        """
        self.upload_id = state.upload_id
        self.parts = state.parts

        return self.upload_id

    async def complete(self) -> str:
        if self.is_upload_in_progress() is False:
            raise NoUploadInProgressError()

        async with self.s3_client() as s3_client:
            response = await s3_client.complete_multipart_upload(
                Bucket=self.bucket_name,
                Key=self.key,
                UploadId=self.upload_id,
                MultipartUpload={"Parts": self.parts},
            )

        self.upload_id = None
        self.parts = []

        return response["Location"]

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

    async def upload_part(self, body: BatchExportTemporaryFile, rewind: bool = True):
        """Upload a part of this multi-part upload."""
        next_part_number = self.part_number + 1

        if rewind is True:
            body.rewind()

        # aiohttp is not duck-type friendly and requires a io.IOBase
        # We comply with the file-like interface of io.IOBase.
        # So we tell mypy to be nice with us.
        reader = io.BufferedReader(body)  # type: ignore

        async with self.s3_client() as s3_client:
            response = await s3_client.upload_part(
                Bucket=self.bucket_name,
                Key=self.key,
                PartNumber=next_part_number,
                UploadId=self.upload_id,
                Body=reader,
            )
        reader.detach()  # BufferedReader closes the file otherwise.

        self.parts.append({"PartNumber": next_part_number, "ETag": response["ETag"]})

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


class HeartbeatDetails(typing.NamedTuple):
    """This tuple allows us to enforce a schema on the Heartbeat details.

    Attributes:
        last_uploaded_part_timestamp: The timestamp of the last part we managed to upload.
        upload_state: State to continue a S3MultiPartUpload when activity execution resumes.
    """

    last_uploaded_part_timestamp: str
    upload_state: S3MultiPartUploadState

    @classmethod
    def from_activity_details(cls, details):
        last_uploaded_part_timestamp = details[0]
        upload_state = S3MultiPartUploadState(*details[1])
        return cls(last_uploaded_part_timestamp, upload_state)


@dataclass
class S3InsertInputs:
    """Inputs for S3 exports."""

    # TODO: do _not_ store credentials in temporal inputs. It makes it very hard
    # to keep track of where credentials are being stored and increases the
    # attach surface for credential leaks.

    bucket_name: str
    region: str
    prefix: str
    team_id: int
    data_interval_start: str
    data_interval_end: str
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    compression: str | None = None
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None
    encryption: str | None = None
    kms_key_id: str | None = None
    batch_export_schema: BatchExportSchema | None = None


async def initialize_and_resume_multipart_upload(inputs: S3InsertInputs) -> tuple[S3MultiPartUpload, str]:
    """Initialize a S3MultiPartUpload and resume it from a hearbeat state if available."""
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="S3")
    key = get_s3_key(inputs)

    s3_upload = S3MultiPartUpload(
        bucket_name=inputs.bucket_name,
        key=key,
        encryption=inputs.encryption,
        kms_key_id=inputs.kms_key_id,
        region_name=inputs.region,
        aws_access_key_id=inputs.aws_access_key_id,
        aws_secret_access_key=inputs.aws_secret_access_key,
    )

    details = activity.info().heartbeat_details

    try:
        interval_start, upload_state = HeartbeatDetails.from_activity_details(details)
    except IndexError:
        # This is the error we expect when no details as the sequence will be empty.
        interval_start = inputs.data_interval_start
        logger.debug(
            "Did not receive details from previous activity Excecution. Export will start from the beginning %s",
            interval_start,
        )
    except Exception:
        # We still start from the beginning, but we make a point to log unexpected errors.
        # Ideally, any new exceptions should be added to the previous block after the first time and we will never land here.
        interval_start = inputs.data_interval_start
        logger.warning(
            "Did not receive details from previous activity Excecution due to an unexpected error. Export will start from the beginning %s",
            interval_start,
        )
    else:
        logger.info(
            "Received details from previous activity. Export will attempt to resume from %s",
            interval_start,
        )
        s3_upload.continue_from_state(upload_state)

        if inputs.compression == "brotli":
            # Even if we receive details we cannot resume a brotli compressed upload as we have lost the compressor state.
            interval_start = inputs.data_interval_start

            logger.info(
                f"Export will start from the beginning as we are using brotli compression: %s",
                interval_start,
            )
            await s3_upload.abort()

    return s3_upload, interval_start


def s3_default_fields() -> list[BatchExportField]:
    """Default fields for an S3 batch export.

    Starting from the common default fields, we add and tweak some fields for
    backwards compatibility.
    """
    batch_export_fields = default_fields()
    batch_export_fields.append({"expression": "elements_chain", "alias": "elements_chain"})
    batch_export_fields.append({"expression": "nullIf(person_properties, '')", "alias": "person_properties"})
    batch_export_fields.append({"expression": "toString(person_id)", "alias": "person_id"})
    # In contrast to other destinations, we do export this field.
    batch_export_fields.append({"expression": "COALESCE(inserted_at, _timestamp)", "alias": "inserted_at"})

    # Again, in contrast to other destinations, and for historical reasons, we do not include these fields.
    not_exported_by_default = {"team_id", "set", "set_once"}

    return [field for field in batch_export_fields if field["alias"] not in not_exported_by_default]


@activity.defn
async def insert_into_s3_activity(inputs: S3InsertInputs):
    """Activity to batch export data from PostHog's ClickHouse to S3.

    It currently only creates a single file per run, and uploads as a multipart upload.

    TODO: this implementation currently tries to export as one run, but it could
    be a very big date range and time consuming, better to split into multiple
    runs, timing out after say 30 seconds or something and upload multiple
    files.
    """
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="S3")
    logger.info(
        "Exporting batch %s - %s",
        inputs.data_interval_start,
        inputs.data_interval_end,
    )

    async with get_client() as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        count = await get_rows_count(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
        )

        if count == 0:
            logger.info(
                "Nothing to export in batch %s - %s",
                inputs.data_interval_start,
                inputs.data_interval_end,
            )
            return

        logger.info("BatchExporting %s rows to S3", count)

        s3_upload, interval_start = await initialize_and_resume_multipart_upload(inputs)

        if inputs.batch_export_schema is None:
            fields = s3_default_fields()
            query_parameters = None

        else:
            fields = inputs.batch_export_schema["fields"]
            query_parameters = inputs.batch_export_schema["values"]

        record_iterator = iter_records(
            client=client,
            team_id=inputs.team_id,
            interval_start=interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            fields=fields,
            extra_query_parameters=query_parameters,
        )

        last_uploaded_part_timestamp: str | None = None

        async def worker_shutdown_handler():
            """Handle the Worker shutting down by heart-beating our latest status."""
            await activity.wait_for_worker_shutdown()
            logger.warn(
                f"Worker shutting down! Reporting back latest exported part {last_uploaded_part_timestamp}",
            )
            if last_uploaded_part_timestamp is None:
                # Don't heartbeat if worker shuts down before we could even send anything
                # Just start from the beginning again.
                return

            activity.heartbeat(last_uploaded_part_timestamp, s3_upload.to_state())

        asyncio.create_task(worker_shutdown_handler())

        record = None

        async with s3_upload as s3_upload:
            with BatchExportTemporaryFile(compression=inputs.compression) as local_results_file:
                rows_exported = get_rows_exported_metric()
                bytes_exported = get_bytes_exported_metric()

                async def flush_to_s3(last_uploaded_part_timestamp: str, last=False):
                    logger.debug(
                        "Uploading %s part %s containing %s records with size %s bytes",
                        "last " if last else "",
                        s3_upload.part_number + 1,
                        local_results_file.records_since_last_reset,
                        local_results_file.bytes_since_last_reset,
                    )

                    await s3_upload.upload_part(local_results_file)
                    rows_exported.add(local_results_file.records_since_last_reset)
                    bytes_exported.add(local_results_file.bytes_since_last_reset)

                    activity.heartbeat(last_uploaded_part_timestamp, s3_upload.to_state())

                for record_batch in record_iterator:
                    for record in record_batch.to_pylist():
                        for json_column in ("properties", "person_properties", "set", "set_once"):
                            if (json_str := record.get(json_column, None)) is not None:
                                record[json_column] = json.loads(json_str)

                        inserted_at = record.pop("_inserted_at")

                        local_results_file.write_records_to_jsonl([record])

                        if local_results_file.tell() > settings.BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES:
                            last_uploaded_part_timestamp = str(inserted_at)
                            await flush_to_s3(last_uploaded_part_timestamp)
                            local_results_file.reset()

                if local_results_file.tell() > 0 and record is not None:
                    last_uploaded_part_timestamp = str(inserted_at)
                    await flush_to_s3(last_uploaded_part_timestamp, last=True)

            await s3_upload.complete()


@workflow.defn(name="s3-export")
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
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)

        create_export_run_inputs = CreateBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        )
        run_id = await workflow.execute_activity(
            create_export_run,
            create_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        update_inputs = UpdateBatchExportRunStatusInputs(
            id=run_id,
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
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            compression=inputs.compression,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            encryption=inputs.encryption,
            kms_key_id=inputs.kms_key_id,
            batch_export_schema=inputs.batch_export_schema,
        )

        await execute_batch_export_insert_activity(
            insert_into_s3_activity,
            insert_inputs,
            non_retryable_error_types=[
                # S3 parameter validation failed.
                "ParamValidationError",
                # This error usually indicates credentials are incorrect or permissions are missing.
                "ClientError",
            ],
            update_inputs=update_inputs,
        )
