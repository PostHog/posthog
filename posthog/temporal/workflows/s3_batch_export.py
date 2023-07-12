import asyncio
import datetime as dt
import io
import json
import typing
from dataclasses import dataclass

import boto3
from django.conf import settings
from temporalio import activity, workflow
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
    get_results_iterator,
    get_rows_count,
)
from posthog.temporal.workflows.clickhouse import get_client


class UploadAlreadyInProgressError(Exception):
    def __init__(self, upload_id):
        super().__init__(f"This upload is already in progress with ID: {upload_id}. Instantiate a new object.")


class NoUploadInProgressError(Exception):
    def __init__(self):
        super().__init__("No multi-part upload is in progress. Call 'create' to start one.")


class S3MultiPartUploadState(typing.NamedTuple):
    upload_id: str
    parts: list[dict[str, str | int]]


class S3MultiPartUpload:
    """Manage an S3MultiPartUpload."""

    def __init__(self, s3_client, bucket_name, key):
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.key = key
        self.upload_id = None
        self.parts = []

    def to_state(self) -> S3MultiPartUploadState:
        if self.is_upload_in_progress() is False or self.upload_id is None:
            raise NoUploadInProgressError()

        return S3MultiPartUploadState(self.upload_id, self.parts)

    @property
    def part_number(self):
        return len(self.parts)

    def is_upload_in_progress(self) -> bool:
        if self.upload_id is None:
            return False
        return True

    def create(self) -> str:
        if self.is_upload_in_progress() is True:
            raise UploadAlreadyInProgressError(self.upload_id)

        multipart_response = self.s3_client.create_multipart_upload(Bucket=self.bucket_name, Key=self.key)
        self.upload_id = multipart_response["UploadId"]

        return self.upload_id

    def continue_from_state(self, state: S3MultiPartUploadState):
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

    def upload_part(self, body: bytes | typing.BinaryIO):
        next_part_number = self.part_number + 1

        if isinstance(body, io.IOBase):
            body.seek(0)

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
            self.create()

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


@activity.defn
async def insert_into_s3_activity(inputs: S3InsertInputs) -> tuple[int, int]:
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
                count,
            )
            return (0, 0)

        activity.logger.info("BatchExporting %s rows to S3", count)

        # Create a multipart upload to S3
        template_variables = get_allowed_template_variables(inputs)
        key_prefix = inputs.prefix.format(**template_variables)
        key = f"{key_prefix}/{inputs.data_interval_start}-{inputs.data_interval_end}.jsonl"
        s3_client = boto3.client(
            "s3",
            region_name=inputs.region,
            aws_access_key_id=inputs.aws_access_key_id,
            aws_secret_access_key=inputs.aws_secret_access_key,
        )
        s3_upload = S3MultiPartUpload(s3_client, inputs.bucket_name, key)

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
            activity.logger.info(f"Received details from previous activity. Export will resume from: {interval_start}")
            s3_upload.continue_from_state(upload_state)

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
        )

        last_uploaded_part_timestamp = None
        with BatchExportTemporaryFile() as local_results_file:
            with s3_upload as s3_upload:

        async def worker_shutdown_handler():
            """Handle the Worker shutting down by heart-beating our latest status."""
            await activity.wait_for_worker_shutdown()
            activity.logger.warn(
                f"Worker shutting down! Reporting back latest exported part {last_uploaded_part_timestamp}"
            )
            activity.heartbeat(last_uploaded_part_timestamp, upload_id)

        asyncio.create_task(worker_shutdown_handler())

        with tempfile.NamedTemporaryFile() as local_results_file:
            while True:
                try:
                    result = results_iterator.__next__()
                except StopIteration:
                    break
                except json.JSONDecodeError:
                    # This is raised by aiochclient as we try to decode an error message from ClickHouse.
                    # So far, this error message only indicated that we were too slow consuming rows.
                    # So, we can resume from the last result.
                    if result is None:
                        # We failed right at the beginning
                        new_interval_start = None
                    else:
                        new_interval_start = result.get("inserted_at", None)

                    if not isinstance(new_interval_start, str):
                        new_interval_start = inputs.data_interval_start

                    activity.logger.warn(
                        f"Worker shutting down! Reporting back latest exported part {last_uploaded_part_timestamp}"
                    )
                    activity.heartbeat(last_uploaded_part_timestamp, s3_upload.to_state())

                asyncio.create_task(worker_shutdown_handler())

                async for result, latest_timestamp in results_iterator:
                    if not result:
                        continue

                # Write the results to a local file
                local_results_file.write(json.dumps(result).encode("utf-8"))
                local_results_file.write("\n".encode("utf-8"))
                records_completed += 1

                    # Write results to S3 when the file reaches 50MB and reset the
                    # file, or if there is nothing else to write.
                    if local_results_file.bytes_since_last_reset > settings.BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES:
                        activity.logger.info("Uploading part %s", s3_upload.part_number + 1)

                    local_results_file.seek(0)
                    response = s3_client.upload_part(
                        Bucket=inputs.bucket_name,
                        Key=key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=local_results_file,
                    )
                    last_uploaded_part_timestamp = result["inserted_at"]
                    # Record the ETag for the part
                    parts.append({"PartNumber": part_number, "ETag": response["ETag"]})
                    part_number += 1

                        local_results_file.reset()

                # Upload the last part
                s3_upload.upload_part(local_results_file)
                activity.heartbeat(last_uploaded_part_timestamp, tuple(s3_upload.to_state()))

        return (local_results_file.records_total, local_results_file.bytes_total)


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

        data_interval_start, data_interval_end = get_data_interval_from_workflow_inputs(inputs)

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
            id=run_id, status="Completed", bytes_completed=0, records_completed=0
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
        )
        try:
            records_completed, bytes_completed = await workflow.execute_activity(
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
                    ],
                ),
            )

        except Exception as e:
            workflow.logger.exception("S3 BatchExport failed.", exc_info=e)
            update_inputs.status = "Failed"
            raise

        else:
            update_inputs.bytes_completed = bytes_completed
            update_inputs.records_completed = records_completed

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


def get_data_interval_from_workflow_inputs(inputs: S3BatchExportInputs) -> tuple[dt.datetime, dt.datetime]:
    """Return the start and end of an export's data interval.

    Args:
        inputs: The S3 BatchExport inputs.

    Raises:
        TypeError: If when trying to obtain the data interval end we run into non-str types.

    Returns:
        A tuple of two dt.datetime indicating start and end of the data_interval.
    """
    data_interval_end_str = inputs.data_interval_end

    if not data_interval_end_str:
        data_interval_end_search_attr = workflow.info().search_attributes.get("TemporalScheduledStartTime")

        # These two if-checks are a bit pedantic, but Temporal SDK is heavily typed.
        # So, they exist to make mypy happy.
        if data_interval_end_search_attr is None:
            msg = (
                "Expected 'TemporalScheduledStartTime' of type 'list[str]' or 'list[datetime], found 'NoneType'."
                "This should be set by the Temporal Schedule unless triggering workflow manually."
                "In the latter case, ensure 'S3BatchExportInputs.data_interval_end' is set."
            )
            raise TypeError(msg)

        # Failing here would perhaps be a bug in Temporal.
        if isinstance(data_interval_end_search_attr[0], str):
            data_interval_end_str = data_interval_end_search_attr[0]
            data_interval_end = dt.datetime.fromisoformat(data_interval_end_str)

        elif isinstance(data_interval_end_search_attr[0], dt.datetime):
            data_interval_end = data_interval_end_search_attr[0]

        else:
            msg = (
                f"Expected search attribute to be of type 'str' or 'datetime' found '{data_interval_end_search_attr[0]}' "
                f"of type '{type(data_interval_end_search_attr[0])}'."
            )
            raise TypeError(msg)
    else:
        data_interval_end = dt.datetime.fromisoformat(data_interval_end_str)

    data_interval_start = data_interval_end - dt.timedelta(seconds=inputs.batch_window_size)

    return (data_interval_start, data_interval_end)
