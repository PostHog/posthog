import json
import time
import uuid
import datetime as dt
import posixpath

from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404

import boto3
import structlog
from botocore.client import Config
from botocore.exceptions import ClientError
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema
from rest_framework import mixins, response, serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError

from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import BatchExportDestination, BatchExportFileDownload, BatchExportOnDemand, BatchExportRun

from products.batch_exports.backend.service import start_file_download_batch_export

SESSION = boto3.Session()
FILE_DOWNLOAD_MAX_RANGE = dt.timedelta(weeks=1)
LOGGER = structlog.get_logger(__name__)


class FileDownloadDestinationFileConfigSerializer(serializers.Serializer):
    """Typed configuration for a FileDownload batch-export destination."""

    format = serializers.ChoiceField(choices=["Parquet", "JSONLines"], default="Parquet", help_text="File format")
    compression = serializers.ChoiceField(
        choices=["zstd", "gzip", "brotli", "lz4", "snappy"],
        required=False,
        default=None,
        allow_null=True,
        help_text="Compress the file with a supported compression format",
    )
    max_size_mb = serializers.IntegerField(
        required=False,
        default=None,
        allow_null=True,
        help_text="Split download into multiple files of at most this size in MB",
    )


class FileDownloadEventsRequestSerializer(serializers.Serializer):
    """Typed configuration for the events model."""

    file = FileDownloadDestinationFileConfigSerializer()
    model = serializers.ChoiceField(choices=["events"])
    include = serializers.ListField(child=serializers.CharField(), required=False)
    exclude = serializers.ListField(child=serializers.CharField(), required=False)
    data_interval_start = serializers.DateTimeField(default_timezone=dt.UTC)
    data_interval_end = serializers.DateTimeField(default_timezone=dt.UTC)


class FileDownloadPersonsRequestSerializer(serializers.Serializer):
    """Typed configuration for the persons model."""

    file = FileDownloadDestinationFileConfigSerializer()
    model = serializers.ChoiceField(choices=["persons"])
    data_interval_start = serializers.DateTimeField(default_timezone=dt.UTC)
    data_interval_end = serializers.DateTimeField(default_timezone=dt.UTC)


class FileDownloadSessionsRequestSerializer(serializers.Serializer):
    """Typed configuration for the sessions model."""

    file = FileDownloadDestinationFileConfigSerializer()
    model = serializers.ChoiceField(choices=["sessions"])
    data_interval_start = serializers.DateTimeField(default_timezone=dt.UTC)
    data_interval_end = serializers.DateTimeField(default_timezone=dt.UTC)


class FileDownloadBatchExportOnDemandSerializer(serializers.Serializer):
    """Request shape for a FileDownload batch export on demand."""

    file = FileDownloadDestinationFileConfigSerializer()
    model = serializers.ChoiceField(choices=["events", "persons", "sessions"])

    # Only specific to events
    include = serializers.ListField(child=serializers.CharField(), required=False)
    exclude = serializers.ListField(child=serializers.CharField(), required=False)

    # Run attributes
    data_interval_start = serializers.DateTimeField(default_timezone=dt.UTC)
    data_interval_end = serializers.DateTimeField(default_timezone=dt.UTC)

    def validate(self, data):
        if data["data_interval_start"] > data["data_interval_end"]:
            raise ValidationError("'data_interval_end' must occur after 'data_interval_start'")

        if data["data_interval_end"] - data["data_interval_start"] > FILE_DOWNLOAD_MAX_RANGE:
            raise ValidationError("data interval range too big")

        return data

    def create(self, validated_data: dict) -> BatchExportRun:
        """Create a `BatchExportRun` based on a `BatchExportOnDemand`.

        This also creates the necessary `BatchExportDestination`.
        """
        team_id = self.context["team_id"]
        config = validated_data.pop("file")

        data_interval_start = validated_data.pop("data_interval_start")
        data_interval_end = validated_data.pop("data_interval_end")

        model = validated_data["model"]
        if (include := validated_data.pop("include", None)) is not None and model == "events":
            config["include_events"] = include

        if (exclude := validated_data.pop("exclude", None)) is not None and model == "events":
            config["exclude_events"] = exclude

        destination = BatchExportDestination(type=BatchExportDestination.Destination.FILE_DOWNLOAD, config=config)
        batch_export = BatchExportOnDemand(team_id=team_id, destination=destination, **validated_data)
        batch_export_run = BatchExportRun(
            status=BatchExportRun.Status.STARTING,
            batch_export_on_demand=batch_export,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
        )

        with transaction.atomic():
            destination.save()
            batch_export.save()
            batch_export_run.save()

        return batch_export_run


class CreateOutputSerializer(serializers.Serializer):
    """Typed output for view set `create`."""

    id = serializers.UUIDField()


class RetrieveBasicOutputSerializer(serializers.Serializer):
    """Typed output for view set `retrieve` with any of the statuses without extra output."""

    status = serializers.ChoiceField(choices=["Starting", "Running", "Cancelled"])


class RetrieveCompletedOutputSerializer(serializers.Serializer):
    """Typed output for view set `retrieve` with completed status."""

    status = serializers.ChoiceField(choices=["Completed"])
    files = serializers.ListField(child=serializers.UUIDField())


class RetrieveFailedOutputSerializer(serializers.Serializer):
    """Typed output for view set `retrieve` with any of the failed statuses."""

    status = serializers.ChoiceField(choices=["Failed", "FailedRetryable", "FailedBilling", "Terminated", "TimedOut"])
    error = serializers.CharField()


class RetrieveOutputSerializer(serializers.Serializer):
    """Retrieve serializer with all fields optional except status.

    The actual conditional shape is described by the polymorphic schema in
    @extend_schema. This serializer exists as a runtime/fallback type.
    """

    status = serializers.ChoiceField(choices=BatchExportRun.Status.choices)
    error = serializers.CharField(required=False)
    files = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
    )


class FileDownloadBatchExportOnDemandViewSet(
    TeamAndOrgViewSetMixin, LogEntryMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    scope_object = "batch_export"
    queryset = (
        BatchExportRun.objects.prefetch_related("batch_export_on_demand__destination")
        .exclude(batch_export_on_demand__deleted=True)
        .filter(batch_export_on_demand__destination__type=BatchExportDestination.Destination.FILE_DOWNLOAD)
        .order_by("-created_at")
        .all()
    )
    serializer_class = FileDownloadBatchExportOnDemandSerializer
    log_source = "batch_exports"
    # Not linked directly with a team, we need to go through batch export
    filter_rewrite_rules = {"team_id": "batch_export_on_demand__team_id"}

    @extend_schema(
        request=PolymorphicProxySerializer(
            component_name="CreateFileDownloadRequest",
            serializers={
                "events": FileDownloadEventsRequestSerializer,
                "persons": FileDownloadPersonsRequestSerializer,
                "sessions": FileDownloadSessionsRequestSerializer,
            },
            resource_type_field_name="model",
        ),
        responses={202: CreateOutputSerializer},
    )
    def create(self, request, *args, **kwargs):
        """Create and start a batch export on demand run to download a file."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()

        try:
            start_file_download_batch_export(
                instance.batch_export_on_demand,
                instance.workflow_id,
                batch_export_run_id=instance.id,
                data_interval_start=instance.data_interval_start,
                data_interval_end=instance.data_interval_end,
                compression=instance.batch_export_on_demand.destination.config.get("compression", None),
                format=instance.batch_export_on_demand.destination.config.get("format", "Parquet"),
                max_size_mb=instance.batch_export_on_demand.destination.config.get("max_size_mb", 0),
            )
        except Exception:
            LOGGER.exception("batch_export_on_demand.fail_to_start")

            instance.latest_error = "Failed to start"
            instance.status = BatchExportRun.Status.FAILED
            instance.save()

            return response.Response(
                {
                    "detail": "The batch export failed to start. Check our status page for any ongoing incidents and try again later."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return response.Response({"id": instance.id}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        responses={
            200: PolymorphicProxySerializer(
                component_name="RetrieveFileDownloadResponse",
                serializers={
                    "Starting": RetrieveBasicOutputSerializer,
                    "Running": RetrieveBasicOutputSerializer,
                    "Cancelled": RetrieveBasicOutputSerializer,
                    "Completed": RetrieveCompletedOutputSerializer,
                    "Failed": RetrieveFailedOutputSerializer,
                    "FailedRetryable": RetrieveFailedOutputSerializer,
                    "FailedBilling": RetrieveFailedOutputSerializer,
                    "TimedOut": RetrieveFailedOutputSerializer,
                    "Terminated": RetrieveFailedOutputSerializer,
                },
                resource_type_field_name="status",
            )
        },
    )
    def retrieve(self, *args, **kwargs) -> response.Response:
        """Get a run of a batch export on demand.

        If the underlying batch export run has completed, we return keys to the
        generated file downloads so that users may download them by making a request
        to /download.
        """
        batch_export_run: BatchExportRun = self.get_object()

        error = {}
        if batch_export_run.latest_error is not None:
            error["error"] = batch_export_run.latest_error

        run_status = batch_export_run.status

        files = {}
        if run_status == BatchExportRun.Status.COMPLETED:
            if batch_export_run.batch_export_on_demand is None:
                raise RuntimeError("Batch export on demand must be defined on this run")

            ids = [
                str(id)
                for id in BatchExportFileDownload.objects.filter(
                    batch_export_run=batch_export_run, team=batch_export_run.batch_export_on_demand.team
                )
                .order_by("key")
                .values_list("id", flat=True)
            ]

            if not ids:
                # There is currently a small delay between the run being set to completed
                # and the file downloads being generated, so we account for that and keep
                # showing running status.
                run_status = BatchExportRun.Status.RUNNING
            else:
                files["files"] = ids

        return response.Response({"status": run_status, **files, **error})

    @action(
        methods=["GET"], detail=True, url_path=r"download(?:/(?P<part>[^/.]+))?", required_scopes=["batch_export:read"]
    )
    def download(self, request, part=None, *args, **kwargs) -> HttpResponseRedirect:
        """Download a file (or a part) from this batch export run.

        Users can provide a part component with an id or index, or no part component at
        all:
        * If part id is included: The file download matching the id is downloaded.
        * If part index is included: The file download matching the index (as ordered
            by key) is downloaded.
        * If no part component is present: If there is only one file downloaded, that
            is downloaded. Otherwise the first one as sorted by key is downloaded.
        """
        batch_export_run: BatchExportRun = self.get_object()

        if batch_export_run.status in (BatchExportRun.Status.RUNNING, BatchExportRun.Status.STARTING):
            raise ValidationError("Batch export run is still in progress")

        if batch_export_run.status in (
            BatchExportRun.Status.TERMINATED,
            BatchExportRun.Status.TIMEDOUT,
            BatchExportRun.Status.FAILED,
            BatchExportRun.Status.FAILED_RETRYABLE,
            BatchExportRun.Status.FAILED_BILLING,
        ):
            raise ValidationError("Batch export run has failed")

        if batch_export_run.status == BatchExportRun.Status.CANCELLED:
            raise ValidationError("Batch export run was cancelled")

        file_download = _get_file_download_for_run(batch_export_run, part)

        default_expiration = dt.timedelta(seconds=settings.BATCH_EXPORTS_FILE_DOWNLOAD_EXPIRATION_SECONDS)
        expiration = _calculate_expiration_for_file_download(file_download, default_expiration=default_expiration)

        pre_signed_url = _generate_s3_pre_signed_url(
            settings.BATCH_EXPORTS_FILE_DOWNLOAD_BUCKET,
            file_download.key,
            role_arn=settings.BATCH_EXPORTS_FILE_DOWNLOAD_ROLE_ARN,
            session_name=f"batch-exports-file-download-{file_download.id}",
            expiration=int(expiration.total_seconds()),
            max_attempts=10 if settings.TEST else 1,
        )

        response = HttpResponseRedirect(redirect_to=pre_signed_url)
        response["Cache-Control"] = "no-store"

        return response


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
            raise ValidationError(f"Invalid file id or index: '{file_id_or_index}'")

        if index < 0 or index >= len(file_downloads):
            raise NotFound(f"No files with index {index}")

        file_download = file_downloads[index]

    else:
        file_download = get_object_or_404(
            BatchExportFileDownload.objects.filter(
                batch_export_run=batch_export_run,
                id=file_download_id,
                team=batch_export_run.batch_export_on_demand.team,
            )
        )

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
            raise ValidationError("This file download has expired")

        expiration = min(remaining, default_expiration)
    else:
        expiration = default_expiration

    return expiration
