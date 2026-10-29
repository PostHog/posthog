"""File download batch exports: on-demand runs that write their output to files a person downloads.

The facade reaches this module through a call-time import, because it imports ``boto3``, the
service layer and the Temporal client, none of which may load on the ``django.setup()`` path.
"""

import json
import time
import uuid
import datetime as dt
import posixpath
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.db.models import QuerySet

import boto3
import structlog
from botocore.client import Config
from botocore.exceptions import ClientError

from posthog.hogql.query import execute_hogql_query

from posthog.models import Team, User
from posthog.temporal.common.client import sync_connect

from products.batch_exports.backend.facade import contracts
from products.batch_exports.backend.hogql_source import (
    apply_hogql_batch_export_modifier_defaults,
    load_hogql_modifiers,
    validate_hogql_query_for_batch_export,
)
from products.batch_exports.backend.models.batch_export import (
    BatchExportDestination,
    BatchExportFileDownload,
    BatchExportOnDemand,
    BatchExportRun,
    BatchExportSource,
)
from products.batch_exports.backend.service import (
    cancel_running_batch_export_run,
    get_batch_export_model,
    start_file_download_batch_export,
)
from products.batch_exports.backend.temporal.record_batch_model import HogQLQueryRecordBatchModel
from products.batch_exports.backend.temporal.sql.common import get_user_hogql_batch_export_query_settings

SESSION = boto3.Session()
LOGGER = structlog.get_logger(__name__)
_FILE_DOWNLOAD_BATCH_EXPORTS_LOCK_KEY = int.from_bytes(
    # 4 ASCII bytes to fill 32-bit PostgreSQL lock key
    b"FDBE",
    byteorder="big",
)
_FAILED_STATUSES = (
    BatchExportRun.Status.TERMINATED,
    BatchExportRun.Status.TIMEDOUT,
    BatchExportRun.Status.FAILED,
    BatchExportRun.Status.FAILED_RETRYABLE,
    BatchExportRun.Status.FAILED_BILLING,
)
_IN_PROGRESS_STATUSES = (BatchExportRun.Status.RUNNING, BatchExportRun.Status.STARTING)


def _file_download_runs(team_id: int) -> QuerySet[BatchExportRun]:
    return (
        BatchExportRun.objects.select_related("batch_export_on_demand__destination", "batch_export_on_demand__team")
        .exclude(batch_export_on_demand__deleted=True)
        .filter(
            batch_export_on_demand__destination__type=BatchExportDestination.Destination.FILE_DOWNLOAD,
            batch_export_on_demand__team_id=team_id,
        )
        .order_by("-created_at", "-id")
    )


def _get_run(team_id: int, run_id: UUID) -> BatchExportRun:
    try:
        return _file_download_runs(team_id).get(id=run_id)
    except BatchExportRun.DoesNotExist as e:
        raise contracts.FileDownloadNotFoundError() from e


def _to_file_download_run(batch_export_run: BatchExportRun) -> contracts.FileDownloadRun:
    run_status = batch_export_run.status
    files: tuple[UUID, ...] | None = None

    if run_status == BatchExportRun.Status.COMPLETED:
        if batch_export_run.batch_export_on_demand is None:
            raise RuntimeError("Batch export on demand must be defined on this run")

        ids = tuple(
            BatchExportFileDownload.objects.filter(
                batch_export_run=batch_export_run, team=batch_export_run.batch_export_on_demand.team
            )
            .order_by("key")
            .values_list("id", flat=True)
        )

        has_data = batch_export_run.records_completed is not None and batch_export_run.records_completed > 0
        if not ids and has_data:
            # There is currently a small delay between the run being set to completed
            # and the file downloads being generated, so we account for that and keep
            # showing running status.
            run_status = BatchExportRun.Status.RUNNING
        else:
            files = ids

    return contracts.FileDownloadRun(
        id=batch_export_run.id,
        status=run_status,
        error=batch_export_run.latest_error,
        files=files,
        records_completed=batch_export_run.records_completed,
    )


def list_file_download_runs(team_id: int, *, offset: int, limit: int) -> tuple[list[BatchExportRun], int]:
    runs = _file_download_runs(team_id)
    return list(runs[offset : offset + limit]), runs.count()


def get_file_download_run(team_id: int, run_id: UUID) -> contracts.FileDownloadRun:
    return _to_file_download_run(_get_run(team_id, run_id))


def _build_run(team_id: int, user_id: int, request: contracts.FileDownloadRequest) -> BatchExportRun:
    config: dict[str, object] = {
        "format": request.format,
        "compression": request.compression,
        "max_size_mb": request.max_size_mb,
    }

    source = None
    if request.model == "hogql":
        source = BatchExportSource(
            team_id=team_id,
            hogql_query=request.hogql_query,
            hogql_modifiers=request.hogql_modifiers,
        )

    if request.include_events is not None and request.model == "events":
        config["include_events"] = list(request.include_events)

    if request.exclude_events is not None and request.model == "events":
        config["exclude_events"] = list(request.exclude_events)

    destination = BatchExportDestination(type=BatchExportDestination.Destination.FILE_DOWNLOAD, config=config)
    batch_export = BatchExportOnDemand(
        team_id=team_id,
        destination=destination,
        source=source,
        last_modified_by_id=user_id,
        model=request.model,
    )
    batch_export_run = BatchExportRun(
        status=BatchExportRun.Status.STARTING,
        batch_export_on_demand=batch_export,
        data_interval_start=request.data_interval_start,
        data_interval_end=request.data_interval_end,
    )

    destination.save()
    if source is not None:
        source.save()
    batch_export.save()
    batch_export_run.save()

    return batch_export_run


def start_file_download(team_id: int, user_id: int, request: contracts.FileDownloadRequest) -> UUID:
    with transaction.atomic():
        # Concurrent requests after the first one to obtain a lock will wait here
        # until transaction is done. This prevents creating batch exports over the
        # limit. Note we use our own 32-bit lock key additional to team_id to avoid
        # conflicts with other parts of the application which may have also
        # obtained a lock based on team_id.
        # NOTE: If team_id ever becomes a 64-bit int update this.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s::integer, %s::integer)",
                (_FILE_DOWNLOAD_BATCH_EXPORTS_LOCK_KEY, team_id),
            )

        current_count = BatchExportRun.objects.filter(
            status__in=_IN_PROGRESS_STATUSES,
            batch_export_on_demand__destination__type=BatchExportDestination.Destination.FILE_DOWNLOAD,
            batch_export_on_demand__team_id=team_id,
            batch_export_on_demand__deleted=False,
        ).count()

        if current_count >= settings.BATCH_EXPORT_MAX_CONCURRENT_ON_DEMAND_PER_TEAM:
            raise contracts.TooManyConcurrentFileDownloadsError()

        instance = _build_run(team_id, user_id, request)

    batch_export_on_demand = instance.batch_export_on_demand
    assert batch_export_on_demand is not None
    destination_config = batch_export_on_demand.destination.config
    try:
        start_file_download_batch_export(
            batch_export_on_demand,
            instance.workflow_id,
            batch_export_run_id=instance.id,
            data_interval_start=instance.data_interval_start,
            data_interval_end=instance.data_interval_end,
            batch_export_model=get_batch_export_model(batch_export_on_demand),
            compression=destination_config.get("compression", None),
            format=destination_config.get("format", "Parquet"),
            max_size_mb=destination_config.get("max_size_mb", 0),
            include_events=destination_config.get("include_events", None),
            exclude_events=destination_config.get("exclude_events", None),
        )
    except Exception as e:
        LOGGER.exception("batch_export_on_demand.fail_to_start")

        instance.latest_error = "Failed to start"
        instance.status = BatchExportRun.Status.FAILED
        instance.save()

        raise contracts.FileDownloadStartError() from e

    return instance.id


def cancel_file_download(team_id: int, run_id: UUID) -> str:
    batch_export_run = _get_run(team_id, run_id)

    if batch_export_run.status not in _IN_PROGRESS_STATUSES:
        raise contracts.InvalidFileDownloadRequestError(
            f"Cannot cancel a run that is in '{batch_export_run.status}' status"
        )

    temporal = sync_connect()
    try:
        cancel_running_batch_export_run(temporal, batch_export_run)
    except Exception as e:
        # It could be the case that the run is already cancelled but our database hasn't been updated yet. In
        # this case, we can just ignore the error but log it for visibility (in case there is an actual issue).
        LOGGER.warning("file_download_batch_export.cancel.failed", exc_info=e)

    batch_export_run.refresh_from_db()

    return batch_export_run.status


def get_file_download_url(team_id: int, run_id: UUID, part: str | None) -> str:
    batch_export_run = _get_run(team_id, run_id)

    if batch_export_run.status in _IN_PROGRESS_STATUSES:
        raise contracts.InvalidFileDownloadRequestError("Batch export run is still in progress")

    if batch_export_run.status in _FAILED_STATUSES:
        raise contracts.InvalidFileDownloadRequestError("Batch export run has failed")

    if batch_export_run.status == BatchExportRun.Status.CANCELLED:
        raise contracts.InvalidFileDownloadRequestError("Batch export run was cancelled")

    file_download = _get_file_download_for_run(batch_export_run, part)

    default_expiration = dt.timedelta(seconds=settings.BATCH_EXPORTS_FILE_DOWNLOAD_EXPIRATION_SECONDS)
    expiration = _calculate_expiration_for_file_download(file_download, default_expiration=default_expiration)

    return _generate_s3_pre_signed_url(
        settings.BATCH_EXPORTS_FILE_DOWNLOAD_BUCKET,
        file_download.key,
        role_arn=settings.BATCH_EXPORTS_FILE_DOWNLOAD_ROLE_ARN,
        session_name=f"batch-exports-file-download-{file_download.id}",
        expiration=int(expiration.total_seconds()),
        max_attempts=10 if settings.TEST else 1,
    )


def count_rows_for_hogql_batch_export(
    team_id: int,
    hogql_query: str,
    timeout: int = 30,
    *,
    user_id: int,
    data_interval_start: dt.datetime | None = None,
    data_interval_end: dt.datetime | None = None,
    hogql_modifiers: dict[str, object] | None = None,
) -> int:
    """Count the rows a HogQL query would produce.

    Raises:
        UnsupportedHogQLQueryError: If the query cannot power a batch export.
    """
    team = Team.objects.get(id=team_id)
    user = User.objects.get(id=user_id)
    modifiers = load_hogql_modifiers(hogql_modifiers)
    validate_hogql_query_for_batch_export(hogql_query, team, user=user, modifiers=modifiers)

    record_batch_model = HogQLQueryRecordBatchModel(team_id=team.pk, hogql_query=hogql_query, user_id=user.pk)
    query_settings = get_user_hogql_batch_export_query_settings()
    query_settings.max_execution_time = timeout

    # `execute_hogql_query` resolves modifiers differently than the batch
    # export, which could potentially affect counts.
    # TODO: How big is the difference? Is it worth aligning these two?
    query_response = execute_hogql_query(
        query=record_batch_model.get_count_hogql_query(data_interval_start, data_interval_end),
        team=team,
        user=user,
        query_type="HogQLBatchExportCountRowsQuery",
        settings=query_settings,
        modifiers=apply_hogql_batch_export_modifier_defaults(team, modifiers),
    )
    return query_response.results[0][0] if query_response.results else 0


def _generate_s3_pre_signed_url(
    bucket: str,
    key: str,
    role_arn: str,
    session_name: str,
    expiration: int = 3600,
    max_attempts: int = 1,
    delay: int = 1,
):
    """Generate a pre-signed URL for given bucket and key.

    The URL will be signed with temporary credentials after assuming the given role.
    The credentials will be scoped to only support a s3:GetObject action on the given
    bucket, key.

    Temporary credentials and the download URL have individual expiration times,
    meaning that the lower of the two is the one that counts as users need both valid
    credentials and a valid URL to use the download URL. So, we set the same
    `expiration` to both. Keep in mind that temporary credentials may only be assumed
    for up to a limit configured in the role itself.
    """
    if max_attempts <= 0:
        raise ValueError("`max_attempts` must be positive")

    filename = posixpath.basename(key)

    if not filename:
        # Should never happen, our keys always end with a filename
        raise ValueError(f"Cannot derive filename from S3 key: {key!r}")

    sts = SESSION.client("sts")

    for attempt in range(1, max_attempts + 1):
        # It may take a few moments for access to be granted, so we retry in a loop
        # This is only relevant for test environments in which roles are created in the
        # moment. Long-lived roles in production should succeed on the first attempt.
        try:
            response = sts.assume_role(
                RoleArn=role_arn,
                RoleSessionName=session_name,
                DurationSeconds=expiration,
                Policy=json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Action": ["s3:GetObject"],
                                "Resource": f"arn:aws:s3:::{bucket}/{key}",
                            },
                        ],
                    }
                ),
            )
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code != "AccessDenied" or attempt == max_attempts:
                raise
            time.sleep(delay * (2 ** (attempt - 1)))  # With default delay: 1s, 2s, 4s, 8s, ...
        else:
            break

    assumed_session = boto3.Session(
        aws_access_key_id=response["Credentials"]["AccessKeyId"],
        aws_secret_access_key=response["Credentials"]["SecretAccessKey"],
        aws_session_token=response["Credentials"]["SessionToken"],
    )
    s3 = assumed_session.client("s3", config=Config(signature_version="s3v4"))

    return s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=expiration,
    )


def _get_file_download_for_run(
    batch_export_run: BatchExportRun, file_id_or_index: str | int | None = None
) -> BatchExportFileDownload:
    """Attempt to fetch a file download for a given batch export run.

    Optionally, for multi-file batch exports, filter by file id or index.
    """
    if batch_export_run.batch_export_on_demand is None:
        raise RuntimeError("Batch export on demand must be defined on this run")

    try:
        file_download_id = uuid.UUID(file_id_or_index)  # type: ignore[arg-type]

    except (ValueError, TypeError, AttributeError):
        file_downloads_query = BatchExportFileDownload.objects.filter(
            batch_export_run=batch_export_run, team=batch_export_run.batch_export_on_demand.team
        ).order_by("key")
        file_downloads: list[BatchExportFileDownload] = list(file_downloads_query)

        try:
            index = int(file_id_or_index) if file_id_or_index is not None else 0
        except (ValueError, TypeError):
            raise contracts.InvalidFileDownloadRequestError(f"Invalid file id or index: '{file_id_or_index}'")

        if index < 0 or index >= len(file_downloads):
            raise contracts.FileDownloadNotFoundError(f"No files with index {index}")

        file_download = file_downloads[index]

    else:
        try:
            file_download = BatchExportFileDownload.objects.get(
                batch_export_run=batch_export_run,
                id=file_download_id,
                team=batch_export_run.batch_export_on_demand.team,
            )
        except BatchExportFileDownload.DoesNotExist as e:
            raise contracts.FileDownloadNotFoundError() from e

    return file_download


def _calculate_expiration_for_file_download(
    file_download: BatchExportFileDownload, default_expiration: dt.timedelta
) -> dt.timedelta:
    """Calculate the expiration for a file download.

    The provided `default_expiration` will be used as fallback if the file download
    contains no `expires_at`.
    """

    if file_download.expires_at is not None:
        now = dt.datetime.now(dt.UTC)
        remaining = file_download.expires_at - now

        if remaining < dt.timedelta(seconds=0):
            raise contracts.InvalidFileDownloadRequestError("This file download has expired")

        expiration = min(remaining, default_expiration)
    else:
        expiration = default_expiration

    return expiration
