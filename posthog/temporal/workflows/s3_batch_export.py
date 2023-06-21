import datetime as dt
import json
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, List

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
    get_results_iterator,
    get_rows_count,
)
from posthog.temporal.workflows.clickhouse import get_client

if TYPE_CHECKING:
    from mypy_boto3_s3.type_defs import CompletedPartTypeDef


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
async def insert_into_s3_activity(inputs: S3InsertInputs):
    """
    Activity streams data from ClickHouse to S3. It currently only creates a
    single file per run, and uploads as a multipart upload.

    TODO: this implementation currently tries to export as one run, but it could
    be a very big date range and time consuming, better to split into multiple
    runs, timing out after say 30 seconds or something and upload multiple
    files.

    TODO: at the moment this doesn't do anything about catching data that might
    be late being ingested into the specified time range. To work around this,
    as a little bit of a hack we should export data only up to an hour ago with
    the assumption that that will give it enough time to settle. I is a little
    tricky with the existing setup to properly partition the data into data we
    have or haven't processed yet. We have `_timestamp` in the events table, but
    this is the time
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
            return

        activity.logger.info("BatchExporting %s rows to S3", count)

        # Create a multipart upload to S3
        key = f"{inputs.prefix}/{inputs.data_interval_start}-{inputs.data_interval_end}.jsonl"
        s3_client = boto3.client(
            "s3",
            region_name=inputs.region,
            aws_access_key_id=inputs.aws_access_key_id,
            aws_secret_access_key=inputs.aws_secret_access_key,
        )
        multipart_response = s3_client.create_multipart_upload(Bucket=inputs.bucket_name, Key=key)
        upload_id = multipart_response["UploadId"]

        # Iterate through chunks of results from ClickHouse and push them to S3
        # as a multipart upload. The intention here is to keep memory usage low,
        # even if the entire results set is large. We receive results from
        # ClickHouse, write them to a local file, and then upload the file to S3
        # when it reaches 50MB in size.
        parts: List[CompletedPartTypeDef] = []
        part_number = 1
        results_iterator = get_results_iterator(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
        )

        with tempfile.NamedTemporaryFile() as local_results_file:
            while True:
                try:
                    result = await results_iterator.__anext__()
                except StopAsyncIteration:
                    break

                if not result:
                    break

                # Write the results to a local file
                local_results_file.write(json.dumps(result).encode("utf-8"))
                local_results_file.write("\n".encode("utf-8"))

                # Write results to S3 when the file reaches 50MB and reset the
                # file, or if there is nothing else to write.
                if (
                    local_results_file.tell()
                    and local_results_file.tell() > settings.BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES
                ):
                    activity.logger.info("Uploading part %s", part_number)

                    local_results_file.seek(0)
                    response = s3_client.upload_part(
                        Bucket=inputs.bucket_name,
                        Key=key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=local_results_file,
                    )

                    # Record the ETag for the part
                    parts.append({"PartNumber": part_number, "ETag": response["ETag"]})

                    part_number += 1

                    # Reset the file
                    local_results_file.seek(0)
                    local_results_file.truncate()

            # Upload the last part
            local_results_file.seek(0)
            response = s3_client.upload_part(
                Bucket=inputs.bucket_name,
                Key=key,
                PartNumber=part_number,
                UploadId=upload_id,
                Body=local_results_file,
            )

            # Record the ETag for the last part
            parts.append({"PartNumber": part_number, "ETag": response["ETag"]})

        # Complete the multipart upload
        s3_client.complete_multipart_upload(
            Bucket=inputs.bucket_name,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )


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
            run_id=workflow.info().run_id,
            workflow_id=workflow.info().workflow_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        )
        run_id = await workflow.execute_activity(
            create_export_run,
            create_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=20),
            schedule_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
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
        )
        try:
            await workflow.execute_activity(
                insert_into_s3_activity,
                insert_inputs,
                start_to_close_timeout=dt.timedelta(minutes=20),
                schedule_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    non_retryable_error_types=[
                        # If we can't connect to ClickHouse, no point in retrying.
                        "ConnectionError",
                        # Validation failed, and will keep failing.
                        "ValueError",
                    ],
                ),
            )

        except Exception as e:
            workflow.logger.exception("S3 BatchExport failed.", exc_info=e)
            update_inputs.status = "Failed"
            raise

        finally:
            await workflow.execute_activity(
                update_export_run_status,
                update_inputs,
                start_to_close_timeout=dt.timedelta(minutes=20),
                schedule_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
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
