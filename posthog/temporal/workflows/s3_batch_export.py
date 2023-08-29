import asyncio
import datetime as dt
import json
import posixpath
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
    get_data_interval,
    get_results_iterator,
    get_rows_count,
)
from posthog.temporal.workflows.clickhouse import get_client

if TYPE_CHECKING:
    from mypy_boto3_s3.type_defs import CompletedPartTypeDef


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
    key = posixpath.join(key_prefix, f"{inputs.data_interval_start}-{inputs.data_interval_end}.jsonl")

    if posixpath.isabs(key):
        # Keys are relative to root dir, so this would add an extra "/"
        key = posixpath.relpath(key, "/")

    return key


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

        # Create a multipart upload to S3
        key = get_s3_key(inputs)
        s3_client = boto3.client(
            "s3",
            region_name=inputs.region,
            aws_access_key_id=inputs.aws_access_key_id,
            aws_secret_access_key=inputs.aws_secret_access_key,
        )

        details = activity.info().heartbeat_details

        parts: List[CompletedPartTypeDef] = []

        if len(details) == 4:
            interval_start, upload_id, parts, part_number = details
            activity.logger.info(f"Received details from previous activity. Export will resume from {interval_start}")

        else:
            multipart_response = s3_client.create_multipart_upload(Bucket=inputs.bucket_name, Key=key)
            upload_id = multipart_response["UploadId"]
            interval_start = inputs.data_interval_start
            part_number = 1

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

        result = None
        last_uploaded_part_timestamp = None

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
                        f"Failed to decode a JSON value while iterating, potentially due to a ClickHouse error. Resuming from {new_interval_start}"
                    )

                    results_iterator = get_results_iterator(
                        client=client,
                        team_id=inputs.team_id,
                        interval_start=new_interval_start,  # This means we'll generate at least one duplicate.
                        interval_end=inputs.data_interval_end,
                    )
                    continue

                if not result:
                    break

                content = json.dumps(
                    {
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
                )

                # Write the results to a local file
                local_results_file.write(content.encode("utf-8"))
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
                    last_uploaded_part_timestamp = result["inserted_at"]
                    # Record the ETag for the part
                    parts.append({"PartNumber": part_number, "ETag": response["ETag"]})
                    part_number += 1

                    activity.heartbeat(last_uploaded_part_timestamp, upload_id, parts, part_number)

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
            activity.heartbeat(last_uploaded_part_timestamp, upload_id, parts, part_number)

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
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError"],
                ),
            )
