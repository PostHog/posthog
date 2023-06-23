import datetime as dt
import json
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, List
from uuid import UUID

import boto3
from django.conf import settings
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import S3BatchExportInputs, afetch_batch_export_run
from posthog.batch_exports.models import afetch_batch_export
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
    get_workflow_scheduled_start_time,
)
from posthog.temporal.workflows.clickhouse import get_client

if TYPE_CHECKING:
    from mypy_boto3_s3.type_defs import CompletedPartTypeDef


@dataclass
class S3InsertInputs:
    """Inputs for S3 exports."""

    run_id: str


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
    activity.logger.info("Running Snowflake export run: %s", inputs.run_id)

    run = await afetch_batch_export_run(UUID(inputs.run_id))
    if run is None:
        activity.logger.info("Run %s does not exist. Exiting.", inputs.run_id)
        return

    export = await afetch_batch_export(run.batch_export_id)
    if export is None:
        activity.logger.info("Run %s has no batch export. Exiting.", run.batch_export_id)
        return

    config = export.destination.config
    bucket_name = config["bucket_name"]
    prefix = config["prefix"]
    aws_access_key_id = config["aws_access_key_id"]
    aws_secret_access_key = config["aws_secret_access_key"]
    region = config["aws_region"]

    async with get_client() as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        count = await get_rows_count(
            client=client,
            team_id=export.team_id,
            interval_start=run.data_interval_start,
            interval_end=run.data_interval_end,
        )

        if count == 0:
            activity.logger.info(
                "Nothing to export in batch %s - %s. Exiting.",
                run.data_interval_start,
                run.data_interval_end,
                count,
            )
            return

        activity.logger.info("BatchExporting %s rows to S3", count)

        # Create a multipart upload to S3
        key = f"{prefix}/{run.data_interval_start}-{run.data_interval_end}.jsonl"
        s3_client = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )
        multipart_response = s3_client.create_multipart_upload(Bucket=bucket_name, Key=key)
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
            team_id=export.team_id,
            interval_start=run.data_interval_start,
            interval_end=run.data_interval_end,
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
                        Bucket=bucket_name,
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
                Bucket=bucket_name,
                Key=key,
                PartNumber=part_number,
                UploadId=upload_id,
                Body=local_results_file,
            )

            # Record the ETag for the last part
            parts.append({"PartNumber": part_number, "ETag": response["ETag"]})

        # Complete the multipart upload
        s3_client.complete_multipart_upload(
            Bucket=bucket_name,
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

        workflow_schedule_time = get_workflow_scheduled_start_time(workflow.info())

        data_interval_end = inputs.data_interval_end or workflow_schedule_time
        if not data_interval_end:
            raise ValueError("Either data_interval_end or TemporalScheduledStartTime must be set")

        create_export_run_inputs = CreateBatchExportRunInputs(
            batch_export_id=inputs.batch_export_id,
            data_interval_end=data_interval_end,
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

        if not run_id:
            raise ValueError("Failed to create BatchExportRun")

        update_inputs = UpdateBatchExportRunStatusInputs(id=run_id, status="Completed")

        insert_inputs = S3InsertInputs(run_id=run_id)
        try:
            await workflow.execute_activity(
                insert_into_s3_activity,
                insert_inputs,
                start_to_close_timeout=dt.timedelta(minutes=20),
                schedule_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    non_retryable_error_types=[
                        # If we can't connect to ClickHouse, no point in
                        # retrying.
                        "ConnectionError",
                        # Validation failed, and will keep failing.
                        "ValueError",
                    ],
                ),
            )

        except Exception as e:
            workflow.logger.exception("Snowflake BatchExport failed.", exc_info=e)
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
