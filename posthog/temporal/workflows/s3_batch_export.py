import asyncio
import datetime as dt
import json
import posixpath
import typing
from dataclasses import dataclass

import boto3
from django.conf import settings
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import S3BatchExportInputs
from posthog.temporal.workflows.base import (
    CreateBatchExportRunInputs,
    PostHogWorkflow,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    update_export_run_status,
)
from posthog.temporal.workflows.batch_exports import (
    BatchExportTemporaryFile,
    get_data_interval,
    get_results_iterator,
    get_rows_count,
)
from posthog.temporal.workflows.clickhouse import get_client


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
    """An S3 multi-part upload."""

    def __init__(self, s3_client, bucket_name: str, key: str, encryption: str | None, kms_key_id: str | None):
        self.s3_client = s3_client
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

    def start(self) -> str:
        """Start this S3MultiPartUpload."""
        if self.is_upload_in_progress() is True:
            raise UploadAlreadyInProgressError(self.upload_id)

        optional_kwargs = {}
        if self.encryption:
            optional_kwargs["ServerSideEncryption"] = self.encryption
        if self.kms_key_id:
            optional_kwargs["SSEKMSKeyId"] = self.kms_key_id

        multipart_response = self.s3_client.create_multipart_upload(
            Bucket=self.bucket_name,
            Key=self.key,
            **optional_kwargs,
        )
        upload_id: str = multipart_response["UploadId"]
        self.upload_id = upload_id

        return upload_id

    def continue_from_state(self, state: S3MultiPartUploadState):
        """Continue this S3MultiPartUpload from a previous state."""
        self.upload_id = state.upload_id
        self.parts = state.parts

        return self.upload_id

    def complete(self) -> str:
        if self.is_upload_in_progress() is False:
            raise NoUploadInProgressError()

        response = self.s3_client.complete_multipart_upload(
            Bucket=self.bucket_name,
            Key=self.key,
            UploadId=self.upload_id,
            MultipartUpload={"Parts": self.parts},
        )

        self.upload_id = None
        self.parts = []

        return response["Location"]

    def abort(self):
        if self.is_upload_in_progress() is False:
            raise NoUploadInProgressError()

        self.s3_client.abort_multipart_upload(
            Bucket=self.bucket_name,
            Key=self.key,
            UploadId=self.upload_id,
        )

        self.upload_id = None
        self.parts = []

    def upload_part(self, body: BatchExportTemporaryFile, rewind: bool = True):
        next_part_number = self.part_number + 1

        if rewind is True:
            body.rewind()

        response = self.s3_client.upload_part(
            Bucket=self.bucket_name,
            Key=self.key,
            PartNumber=next_part_number,
            UploadId=self.upload_id,
            Body=body,
        )

        self.parts.append({"PartNumber": next_part_number, "ETag": response["ETag"]})

    def __enter__(self):
        if not self.is_upload_in_progress():
            self.start()

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_value is None:
            # Succesfully completed the upload
            self.complete()
            return True

        if exc_type == asyncio.CancelledError:
            # Ensure we clean-up the cancelled upload.
            self.abort()

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
        return HeartbeatDetails(last_uploaded_part_timestamp, upload_state)


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
    encryption: str | None = None
    kms_key_id: str | None = None


def initialize_and_resume_multipart_upload(inputs: S3InsertInputs) -> tuple[S3MultiPartUpload, str]:
    """Initialize a S3MultiPartUpload and resume it from a hearbeat state if available."""
    key = get_s3_key(inputs)
    s3_client = boto3.client(
        "s3",
        region_name=inputs.region,
        aws_access_key_id=inputs.aws_access_key_id,
        aws_secret_access_key=inputs.aws_secret_access_key,
    )
    s3_upload = S3MultiPartUpload(s3_client, inputs.bucket_name, key, inputs.encryption, inputs.kms_key_id)

    details = activity.info().heartbeat_details

    try:
        interval_start, upload_state = HeartbeatDetails.from_activity_details(details)
    except IndexError:
        # This is the error we expect when no details as the sequence will be empty.
        interval_start = inputs.data_interval_start
        activity.logger.info(
            f"Did not receive details from previous activity Excecution. Export will start from the beginning: {interval_start}"
        )
    except Exception as e:
        # We still start from the beginning, but we make a point to log unexpected errors.
        # Ideally, any new exceptions should be added to the previous block after the first time and we will never land here.
        interval_start = inputs.data_interval_start
        activity.logger.warning(
            f"Did not receive details from previous activity Excecution due to an unexpected error. Export will start from the beginning: {interval_start}",
            exc_info=e,
        )
    else:
        activity.logger.info(
            f"Received details from previous activity. Export will attempt to resume from: {interval_start}"
        )
        s3_upload.continue_from_state(upload_state)

        if inputs.compression == "brotli":
            # Even if we receive details we cannot resume a brotli compressed upload as we have lost the compressor state.
            interval_start = inputs.data_interval_start

            activity.logger.info(
                f"Export will start from the beginning as we are using brotli compression: {interval_start}"
            )
            s3_upload.abort()

    return s3_upload, interval_start


@activity.defn
async def insert_into_s3_activity(inputs: S3InsertInputs):
    """
    Activity streams data from ClickHouse to S3. It currently only creates a
    single file per run, and uploads as a multipart upload.

    TODO: this implementation currently tries to export as one run, but it could
    be a very big date range and time consuming, better to split into multiple
    runs, timing out after say 30 seconds or something and upload multiple
    files.
    """
    activity.logger.info("Running S3 export batch %s - %s", inputs.data_interval_start, inputs.data_interval_end)

    async with get_client() as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        count = await get_rows_count(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
        )

        if count == 0:
            activity.logger.info(
                "Nothing to export in batch %s - %s. Exiting.",
                inputs.data_interval_start,
                inputs.data_interval_end,
            )
            return

        activity.logger.info("BatchExporting %s rows to S3", count)

        s3_upload, interval_start = initialize_and_resume_multipart_upload(inputs)

        # Iterate through chunks of results from ClickHouse and push them to S3
        # as a multipart upload. The intention here is to keep memory usage low,
        # even if the entire results set is large. We receive results from
        # ClickHouse, write them to a local file, and then upload the file to S3
        # when it reaches 50MB in size.

        results_iterator = get_results_iterator(
            client=client,
            team_id=inputs.team_id,
            interval_start=interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
        )

        result = None
        last_uploaded_part_timestamp = None

        async def worker_shutdown_handler():
            """Handle the Worker shutting down by heart-beating our latest status."""
            await activity.wait_for_worker_shutdown()
            activity.logger.warn(
                f"Worker shutting down! Reporting back latest exported part {last_uploaded_part_timestamp}"
            )
            activity.heartbeat(last_uploaded_part_timestamp, s3_upload.to_state())

        asyncio.create_task(worker_shutdown_handler())

        with s3_upload as s3_upload:
            with BatchExportTemporaryFile(compression=inputs.compression) as local_results_file:
                for result in results_iterator:
                    record = {
                        "created_at": result["created_at"],
                        "distinct_id": result["distinct_id"],
                        "elements_chain": result["elements_chain"],
                        "event": result["event"],
                        "inserted_at": result["inserted_at"],
                        "person_id": result["person_id"],
                        "person_properties": result["person_properties"],
                        "properties": result["properties"],
                        "timestamp": result["timestamp"],
                        "uuid": result["uuid"],
                    }

                    local_results_file.write_records_to_jsonl([record])

                    if local_results_file.tell() > settings.BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES:
                        activity.logger.info(
                            "Uploading part %s containing %s records with size %s bytes to S3",
                            s3_upload.part_number + 1,
                            local_results_file.records_since_last_reset,
                            local_results_file.bytes_since_last_reset,
                        )

                        s3_upload.upload_part(local_results_file)

                        last_uploaded_part_timestamp = result["inserted_at"]
                        activity.heartbeat(last_uploaded_part_timestamp, s3_upload.to_state())

                        local_results_file.reset()

                if local_results_file.tell() > 0 and result is not None:
                    activity.logger.info(
                        "Uploading last part %s containing %s records with size %s bytes to S3",
                        s3_upload.part_number + 1,
                        local_results_file.records_since_last_reset,
                        local_results_file.bytes_since_last_reset,
                    )

                    s3_upload.upload_part(local_results_file)

                    last_uploaded_part_timestamp = result["inserted_at"]
                    activity.heartbeat(last_uploaded_part_timestamp, s3_upload.to_state())


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
        workflow.logger.info("Starting S3 export")

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

        update_inputs = UpdateBatchExportRunStatusInputs(id=run_id, status="Completed")

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
            encryption=inputs.encryption,
            kms_key_id=inputs.kms_key_id,
        )
        try:
            await workflow.execute_activity(
                insert_into_s3_activity,
                insert_inputs,
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=120),
                    maximum_attempts=10,
                    non_retryable_error_types=[
                        # S3 parameter validation failed.
                        "ParamValidationError",
                        # This error usually indicates credentials are incorrect or permissions are missing.
                        "ClientError",
                    ],
                ),
            )

        except exceptions.ActivityError as e:
            if isinstance(e.cause, exceptions.CancelledError):
                workflow.logger.exception("S3 BatchExport was cancelled.")
                update_inputs.status = "Cancelled"
            else:
                workflow.logger.exception("S3 BatchExport failed.", exc_info=e)
                update_inputs.status = "Failed"

            update_inputs.latest_error = str(e.cause)
            raise

        except Exception as e:
            workflow.logger.exception("S3 BatchExport failed with an unexpected exception.", exc_info=e)
            update_inputs.status = "Failed"
            update_inputs.latest_error = "An unexpected error has ocurred"
            raise

        finally:
            await workflow.execute_activity(
                update_export_run_status,
                update_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError"],
                ),
            )
