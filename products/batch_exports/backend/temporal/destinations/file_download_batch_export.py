import re
import json
import uuid
import typing
import asyncio
import datetime as dt
import dataclasses

from django.conf import settings

import aioboto3
from botocore.exceptions import ClientError
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportFileDownload
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.service import BatchExportInsertInputs, FileDownloadBatchExportInputs
from products.batch_exports.backend.temporal.batch_exports import (
    OverBillingLimitError,
    StartBatchExportRunInputs,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    S3BatchExportResult,
    S3InsertInputs,
    insert_into_s3_activity_from_stage,
    s3_default_fields,
)
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.utils import handle_non_retryable_errors

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger()
FILE_DOWNLOAD_PREFIX = (
    "batch-exports/{batch_export_id}/{batch_export_run_id}/{{data_interval_start}}-{{data_interval_end}}"
)

NON_RETRYABLE_ERROR_TYPES = ()


class Credentials(typing.NamedTuple):
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_session_token: str


async def _get_temporary_credentials_for_multipart_upload(
    bucket: str, prefix: str, /, role_arn: str, duration: int = 3600
) -> Credentials:
    """Get temporary AWS credentials for a multipart upload to keys under prefix."""
    creds = await _get_temporary_credentials_for_bucket_prefix(
        bucket,
        prefix,
        role_arn=role_arn,
        session_name="batch-exports-file-download-multipart-upload",
        actions=["s3:PutObject", "s3:AbortMultipartUpload"],
        duration=duration,
    )
    return creds


async def _get_temporary_credentials_to_head_object(
    bucket: str, prefix: str, /, role_arn: str, duration: int = 900
) -> Credentials:
    """Get temporary AWS credentials for HEAD object requests for keys under prefix."""
    creds = await _get_temporary_credentials_for_bucket_prefix(
        bucket,
        prefix,
        role_arn=role_arn,
        session_name="batch-exports-file-download-head-object",
        actions=["s3:GetObject"],
        duration=duration,
    )
    return creds


async def _get_temporary_credentials_for_bucket_prefix(
    bucket: str,
    prefix: str,
    /,
    role_arn: str,
    session_name: str,
    actions: list[str],
    duration: int = 3600,
    max_attempts: int = 5,
    delay: int | float = 1.0,
) -> Credentials:
    """Get temporary credentials scoped to operate only on the bucket's prefix.

    The credentials should be limited to a set of actions using the `actions` argument.
    Thus, this should not be called directly, rather call
    `_get_temporary_credentials_for_multipart_upload` or
    `_get_temporary_credentials_to_head_object` as needed.
    """
    session = aioboto3.Session()

    async with session.client("sts") as sts:
        for attempt in range(1, max_attempts + 1):
            try:
                response = await sts.assume_role(
                    RoleArn=role_arn,
                    RoleSessionName=session_name,
                    DurationSeconds=duration,
                    Policy=json.dumps(
                        {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": actions,
                                    "Resource": f"arn:aws:s3:::{bucket}/{prefix}/*",
                                },
                            ],
                        }
                    ),
                )
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code != "AccessDenied" or attempt == max_attempts:
                    raise

                await asyncio.sleep(delay * (2**attempt))

    return Credentials(
        response["Credentials"]["AccessKeyId"],
        response["Credentials"]["SecretAccessKey"],
        response["Credentials"]["SessionToken"],
    )


def parse_expiration(expiration: str | dt.datetime | None) -> dt.datetime | None:
    """Parse an expiration string returned by AWS to extract the expiry-date."""
    if expiration is None:
        return None

    if isinstance(expiration, dt.datetime):
        return expiration

    match = re.search(r'expiry-date="([^"]+)"', expiration)

    if match is None:
        return None

    date_str = match.group(1)
    expiry_date = dt.datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=dt.UTC)

    return expiry_date


@dataclasses.dataclass
class S3Bucket:
    name: str
    region: str


@dataclasses.dataclass
class GenerateFileDownloadsInputs:
    team_id: int
    batch_export_id: str
    batch_export_run_id: str
    s3_bucket: S3Bucket
    aws_role_arn: str
    keys: tuple[str, ...]


FileDownloadIds = list[uuid.UUID]


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def generate_file_downloads(inputs: GenerateFileDownloadsInputs) -> FileDownloadIds:
    """Generate file downloads for given keys."""
    existing = [
        file_download
        async for file_download in BatchExportFileDownload.objects.filter(
            team_id=inputs.team_id, key__in=inputs.keys
        ).all()
    ]
    file_downloads = [file_download.id for file_download in existing]
    keys = set(inputs.keys) - {file_download.key for file_download in existing}

    if not keys:
        # There is nothing to do, maybe we completed everything in a previous attempt.
        return file_downloads

    async with Heartbeater():
        credentials = await _get_temporary_credentials_to_head_object(
            inputs.s3_bucket.name,
            f"batch-exports/{inputs.batch_export_id}/{inputs.batch_export_run_id}",
            role_arn=inputs.aws_role_arn,
        )
        session = aioboto3.Session(
            aws_access_key_id=credentials.aws_access_key_id,
            aws_secret_access_key=credentials.aws_secret_access_key,
            aws_session_token=credentials.aws_session_token,
        )

        async with session.client("s3") as s3:

            async def create_file_download(key: str):
                object = await s3.head_object(Bucket=inputs.s3_bucket.name, Key=key)

                expires_at = parse_expiration(object.get("Expiration"))
                file_download = await BatchExportFileDownload.objects.acreate(
                    team_id=inputs.team_id,
                    key=key,
                    expires_at=expires_at,
                    batch_export_run_id=inputs.batch_export_run_id,
                )
                file_downloads.append(file_download.id)

            async with asyncio.TaskGroup() as tg:
                for key in keys:
                    tg.create_task(create_file_download(key))

    return file_downloads


@dataclasses.dataclass
class ExportInputs:
    batch_export: BatchExportInsertInputs
    s3_bucket: S3Bucket
    aws_role_arn: str
    compression: str | None = None
    file_format: str = "JSONLines"
    max_file_size_mb: int | None = None


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def export_to_file_download_bucket_with_temporary_credentials(inputs: ExportInputs) -> S3BatchExportResult:
    """Export to S3 file download bucket using temporary AWS credentials.

    After obtaining the credentials, we simply run the same function as an S3 batch
    export targeting our own file download bucket.
    """
    prefix = FILE_DOWNLOAD_PREFIX.format(
        batch_export_id=inputs.batch_export.batch_export_id, batch_export_run_id=inputs.batch_export.run_id
    )

    credentials = await _get_temporary_credentials_for_multipart_upload(
        inputs.s3_bucket.name,
        f"batch-exports/{inputs.batch_export.batch_export_id}/{inputs.batch_export.run_id}",
        role_arn=inputs.aws_role_arn,
    )

    s3_insert_inputs = S3InsertInputs(
        bucket_name=inputs.s3_bucket.name,
        region=inputs.s3_bucket.region,
        prefix=prefix,
        compression=inputs.compression,
        file_format=inputs.file_format,
        max_file_size_mb=inputs.max_file_size_mb,
        aws_access_key_id=credentials.aws_access_key_id,
        aws_secret_access_key=credentials.aws_secret_access_key,
        aws_session_token=credentials.aws_session_token,
        data_interval_start=inputs.batch_export.data_interval_start,
        data_interval_end=inputs.batch_export.data_interval_end,
        exclude_events=inputs.batch_export.exclude_events,
        include_events=inputs.batch_export.include_events,
        team_id=inputs.batch_export.team_id,
        run_id=inputs.batch_export.run_id,
        stage_folder=inputs.batch_export.stage_folder,
        batch_export_model=inputs.batch_export.batch_export_model,
        batch_export_id=inputs.batch_export.batch_export_id,
        destination_default_fields=inputs.batch_export.destination_default_fields,
    )
    result = await insert_into_s3_activity_from_stage(s3_insert_inputs)

    return result


@dataclasses.dataclass
class FileDownloadBatchExportResult(BatchExportResult):
    file_downloads: FileDownloadIds = dataclasses.field(default_factory=list)


@workflow.defn(name="file-download-export", failure_exception_types=[workflow.NondeterminismError])
class FileDownloadBatchExportWorkflow(PostHogWorkflow):
    """Workflow to generate files for download from an S3 bucket.

    The workflow works by executing what is essentially an S3 batch export, but
    targeting one of our own buckets. Afterwards, the workflow generates file-download
    models so that the files in our own bucket can be downloaded after generating a
    pre-signed URL.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> FileDownloadBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return FileDownloadBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: FileDownloadBatchExportInputs) -> FileDownloadBatchExportResult:
        """Run the workflow.

        Starts off with the same activities as an S3 batch export, but with some changes
        to utilize our own buckets and credentials.

        Ends with generating the necessary objects for later generating pre-signed URLs.

        Notably, this workflow can be scheduled and ran outside of a schedule. So we
        use the data bounds when they are set.
        """
        if inputs.data_interval_start and inputs.data_interval_end:
            # Allow this workflow to be ran outside of a schedule
            data_interval_end_dt = dt.datetime.fromisoformat(inputs.data_interval_end)
            data_interval_start_dt = dt.datetime.fromisoformat(inputs.data_interval_start)
            should_backfill_from_beginning = False
        else:
            is_backfill = inputs.get_is_backfill()
            is_earliest_backfill = inputs.get_is_earliest_backfill()
            data_interval_start_dt, data_interval_end_dt = get_data_interval(
                inputs.interval, inputs.data_interval_end, inputs.timezone
            )

            should_backfill_from_beginning = is_backfill and is_earliest_backfill

        interval_delta = data_interval_end_dt - data_interval_start_dt

        if inputs.batch_export_run_id is not None:
            run_id = str(inputs.batch_export_run_id)
        else:
            start_batch_export_run_inputs = StartBatchExportRunInputs(
                team_id=inputs.team_id,
                batch_export_id=inputs.batch_export_id,
                data_interval_start=data_interval_start_dt.isoformat(),
                data_interval_end=data_interval_end_dt.isoformat(),
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
                return FileDownloadBatchExportResult(records_completed=0, bytes_exported=0)

        export_inputs = ExportInputs(
            batch_export=BatchExportInsertInputs(
                team_id=inputs.team_id,
                run_id=run_id,
                batch_export_model=inputs.batch_export_model,
                batch_export_id=inputs.batch_export_id,
                exclude_events=inputs.exclude_events,
                include_events=inputs.include_events,
                data_interval_start=data_interval_start_dt.isoformat() if not should_backfill_from_beginning else None,
                data_interval_end=data_interval_end_dt.isoformat(),
                destination_default_fields=s3_default_fields(),
            ),
            s3_bucket=S3Bucket(
                name=settings.BATCH_EXPORTS_FILE_DOWNLOAD_BUCKET,
                region=settings.BATCH_EXPORTS_FILE_DOWNLOAD_REGION,
            ),
            aws_role_arn=settings.BATCH_EXPORTS_FILE_DOWNLOAD_ROLE_ARN,
            compression=inputs.compression,
            file_format=inputs.file_format,
            max_file_size_mb=inputs.max_file_size_mb,
        )
        result: S3BatchExportResult = await execute_batch_export_using_internal_stage(
            export_to_file_download_bucket_with_temporary_credentials,
            export_inputs,  # type: ignore
            interval=f"every {int(interval_delta.total_seconds())} seconds",
        )

        file_downloads = await workflow.execute_activity(
            generate_file_downloads,
            GenerateFileDownloadsInputs(
                team_id=inputs.team_id,
                batch_export_id=inputs.batch_export_id,
                batch_export_run_id=run_id,
                s3_bucket=S3Bucket(
                    name=settings.BATCH_EXPORTS_FILE_DOWNLOAD_BUCKET,
                    region=settings.BATCH_EXPORTS_FILE_DOWNLOAD_REGION,
                ),
                keys=tuple(result.files_uploaded),
                aws_role_arn=settings.BATCH_EXPORTS_FILE_DOWNLOAD_ROLE_ARN,
            ),
            start_to_close_timeout=dt.timedelta(minutes=5),
            heartbeat_timeout=dt.timedelta(seconds=10),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=1),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
            ),
        )

        return FileDownloadBatchExportResult(
            records_completed=result.records_completed,
            bytes_exported=result.bytes_exported,
            file_downloads=file_downloads,
        )
