import datetime as dt
from typing import Any, cast

from django.db import models
from django.http import HttpResponseRedirect

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
    extend_schema_view,
)
from rest_framework import response, serializers, status, viewsets
from rest_framework.exceptions import APIException, NotAuthenticated, NotFound, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.throttling import BaseThrottle

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.log_entries import LogEntryMixin
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.errors import ExposedCHQueryError
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models import User
from posthog.rate_limit import BatchExportsCountRowsBurstRateThrottle, BatchExportsCountRowsSustainedRateThrottle

from products.batch_exports.backend.facade import (
    api as batch_exports_api,
    contracts,
)
from products.batch_exports.backend.facade.enums import BatchExportRunStatus
from products.batch_exports.backend.presentation.views.utils import (
    HOGQL_MODIFIERS_HELP_TEXT,
    HogQLModifiersField,
    check_hogql_batch_exports_enabled,
    parse_path_uuid,
)

FILE_DOWNLOAD_MAX_RANGE = dt.timedelta(weeks=1)
DEFAULT_MAX_SIZE_MB = 1024
# The viewset declares no queryset, so drf-spectacular cannot read the type of the id from a model.
RUN_ID_PARAMETER = OpenApiParameter(
    "id", OpenApiTypes.UUID, OpenApiParameter.PATH, description="A UUID string identifying this batch export run."
)


class FileFormat(models.TextChoices):
    PARQUET = "Parquet", "Parquet"
    JSONLINES = "JSONLines", "JSONLines"


class FileDownloadHogQLModel(models.TextChoices):
    HOGQL = "hogql", "hogql"


class FileDownloadDestinationFileConfigSerializer(serializers.Serializer):
    """Typed configuration for a FileDownload batch-export destination."""

    format = serializers.ChoiceField(choices=FileFormat.choices, default="Parquet", help_text="File format")
    compression = serializers.ChoiceField(
        choices=["zstd", "gzip", "brotli", "lz4", "snappy"],
        required=False,
        default=None,
        allow_null=True,
        help_text="Compress the file with a supported compression format",
    )
    max_size_mb = serializers.IntegerField(
        required=False,
        default=DEFAULT_MAX_SIZE_MB,
        allow_null=True,
        min_value=0,
        help_text="Split the download into files of about this size in MiB. A file can go a little "
        "over. Set it to null or 0 to write a single file of any size.",
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


HOGQL_QUERY_HELP_TEXT = (
    "HogQL SELECT query whose results are exported. This model is in closed beta and is enabled "
    "per team; when it is not enabled, the request fails with a permission error that names HogQL "
    "batch exports. Contact PostHog support to request access. The query may reference the "
    "{data_interval_start} and {data_interval_end} placeholders. Provide a value for each "
    "placeholder the query references; missing referenced bounds are rejected, not inferred. "
    "When both bounds are supplied, they must span at most seven days. Neither supplied bound may be in the future. "
    "Without placeholders, the query runs unchanged, even if bounds are supplied. Every column "
    "in the SELECT clause must be a field or have an alias. It is recommended to limit the query "
    "with a WHERE clause, for example bounding timestamp on the events table, both to avoid "
    "exporting more rows than expected and because user queries run under stricter resource "
    "limits than the other models."
)


DATA_INTERVAL_START_HELP_TEXT = (
    "Start of the export interval. Required for the events, persons, and sessions models. "
    "For HogQL, required only when the query references {data_interval_start}. "
    "A supplied start must not be in the future. "
    "When both bounds are supplied, the interval must span at most seven days."
)
DATA_INTERVAL_END_HELP_TEXT = (
    "End of the export interval. Required for the events, persons, and sessions models. "
    "For HogQL, required only when the query references {data_interval_end}. "
    "A supplied end must not be in the future or precede a supplied start. "
    "Bounds replace HogQL placeholders; they do not add filters to the query."
)


def validate_file_download_interval(
    data_interval_start: dt.datetime | None,
    data_interval_end: dt.datetime | None,
    *,
    hogql_query: str | None = None,
) -> None:
    if hogql_query is not None:
        try:
            placeholders = batch_exports_api.find_hogql_interval_placeholders(hogql_query)
        except contracts.UnsupportedHogQLQueryError as e:
            raise ValidationError({"hogql_query": str(e)}) from e
        bounds = {"data_interval_start": data_interval_start, "data_interval_end": data_interval_end}
        missing = {
            name: f"'{name}' is required because the query references '{{{name}}}'."
            for name in sorted(placeholders)
            if bounds[name] is None
        }
        if missing:
            raise ValidationError(missing)
    elif data_interval_start is None or data_interval_end is None:
        raise ValidationError("'data_interval_start' and 'data_interval_end' are required. Provide both bounds.")
    if data_interval_start is not None and data_interval_end is not None:
        if data_interval_start > data_interval_end:
            raise ValidationError("'data_interval_end' must occur after 'data_interval_start'")
        if data_interval_end - data_interval_start > FILE_DOWNLOAD_MAX_RANGE:
            raise ValidationError("data interval range too big. Choose an interval of at most seven days.")
    now = dt.datetime.now(dt.UTC)
    if data_interval_start is not None and data_interval_start > now:
        raise ValidationError(
            f"The provided 'data_interval_start' ({data_interval_start.isoformat()}) is in the future"
        )
    if data_interval_end is not None and data_interval_end > now:
        raise ValidationError(f"The provided 'data_interval_end' ({data_interval_end.isoformat()}) is in the future")


class FileDownloadHogQLRequestSerializer(serializers.Serializer):
    """Typed configuration for the hogql model."""

    file = FileDownloadDestinationFileConfigSerializer()
    model = serializers.ChoiceField(choices=FileDownloadHogQLModel.choices)
    hogql_query = serializers.CharField(help_text=HOGQL_QUERY_HELP_TEXT)
    hogql_modifiers = HogQLModifiersField(required=False, help_text=HOGQL_MODIFIERS_HELP_TEXT)
    data_interval_start = serializers.DateTimeField(
        default_timezone=dt.UTC, required=False, help_text=DATA_INTERVAL_START_HELP_TEXT
    )
    data_interval_end = serializers.DateTimeField(
        default_timezone=dt.UTC, required=False, help_text=DATA_INTERVAL_END_HELP_TEXT
    )


class FileDownloadCountRowsRequestSerializer(serializers.Serializer):
    """Request shape for counting the rows a file download batch export would produce."""

    model = serializers.ChoiceField(
        choices=FileDownloadHogQLModel.choices,
        help_text="Model to count rows for. Only 'hogql' is supported.",
    )
    hogql_query = serializers.CharField(help_text=HOGQL_QUERY_HELP_TEXT)
    hogql_modifiers = HogQLModifiersField(required=False, help_text=HOGQL_MODIFIERS_HELP_TEXT)
    data_interval_start = serializers.DateTimeField(
        default_timezone=dt.UTC, required=False, help_text=DATA_INTERVAL_START_HELP_TEXT
    )
    data_interval_end = serializers.DateTimeField(
        default_timezone=dt.UTC, required=False, help_text=DATA_INTERVAL_END_HELP_TEXT
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        validate_file_download_interval(
            data.get("data_interval_start"), data.get("data_interval_end"), hogql_query=data["hogql_query"]
        )
        return data


class FileDownloadCountRowsResponseSerializer(serializers.Serializer):
    """Typed output for view set `count_rows`."""

    count = serializers.IntegerField(
        min_value=0,
        help_text="Number of rows the query returns with the supplied interval bounds. "
        "Data arriving between counting and exporting can change the result.",
    )


COUNT_ROWS_TIMEOUT_MESSAGE = (
    "Timeout exceeded while counting rows. The query may be too complex, or the count may be too "
    "large to finish within a short time. Running this query in an export may take too long to "
    "complete and/or may produce a very large file to download. Narrow the query with a WHERE "
    "clause to count and export less data if you can't tolerate the additional execution time "
    "and/or file size."
)


class FileDownloadBatchExportOnDemandSerializer(serializers.Serializer):
    """Request shape for a FileDownload batch export on demand."""

    file = FileDownloadDestinationFileConfigSerializer()
    model = serializers.ChoiceField(choices=["events", "persons", "sessions", "hogql"])

    # Only specific to events
    include = serializers.ListField(child=serializers.CharField(), required=False)
    exclude = serializers.ListField(child=serializers.CharField(), required=False)

    # Only specific to hogql
    hogql_query = serializers.CharField(required=False, help_text=HOGQL_QUERY_HELP_TEXT)
    hogql_modifiers = HogQLModifiersField(required=False, help_text=HOGQL_MODIFIERS_HELP_TEXT)

    data_interval_start = serializers.DateTimeField(
        default_timezone=dt.UTC, required=False, help_text=DATA_INTERVAL_START_HELP_TEXT
    )
    data_interval_end = serializers.DateTimeField(
        default_timezone=dt.UTC, required=False, help_text=DATA_INTERVAL_END_HELP_TEXT
    )

    def validate(self, data):
        if data["model"] == "hogql":
            return self._validate_hogql(data)

        if data.get("hogql_query") is not None:
            raise ValidationError("'hogql_query' is only supported when 'model' is 'hogql'")

        if data.get("hogql_modifiers") is not None:
            raise ValidationError("'hogql_modifiers' are only supported when 'model' is 'hogql'")

        validate_file_download_interval(data.get("data_interval_start"), data.get("data_interval_end"))

        return data

    def _validate_hogql(self, data: dict) -> dict:
        team = self.context["get_team"]()
        check_hogql_batch_exports_enabled(team)

        if data.get("include") is not None or data.get("exclude") is not None:
            raise ValidationError("'include' and 'exclude' are not supported when 'model' is 'hogql'")

        hogql_query = data.get("hogql_query")
        if not hogql_query:
            raise ValidationError("'hogql_query' is required when 'model' is 'hogql'")

        validate_file_download_interval(
            data.get("data_interval_start"), data.get("data_interval_end"), hogql_query=hogql_query
        )

        try:
            batch_exports_api.validate_hogql_query(
                team.pk,
                user_id=self.context["request"].user.pk,
                hogql_query=hogql_query,
                hogql_modifiers=data.get("hogql_modifiers"),
            )
        except contracts.UnsupportedHogQLQueryError as e:
            raise ValidationError({"hogql_query": str(e)}) from e

        return data


class CreateOutputSerializer(serializers.Serializer):
    """Typed output for view set `create`."""

    id = serializers.UUIDField()


class ListOutputSerializer(serializers.Serializer):
    """Typed output for view set `list`."""

    id = serializers.UUIDField(help_text="ID of the file download batch export run.")
    status = serializers.ChoiceField(
        choices=BatchExportRunStatus.choices,
        help_text="Current status of the file download batch export run.",
    )


class RetrieveBasicOutputSerializer(serializers.Serializer):
    """Typed output for view set `retrieve` with any of the statuses without extra output."""

    status = serializers.ChoiceField(choices=["Starting", "Running", "Cancelled"])


class RetrieveCompletedOutputSerializer(serializers.Serializer):
    """Typed output for view set `retrieve` with completed status."""

    status = serializers.ChoiceField(choices=["Completed"])
    files = serializers.ListField(child=serializers.UUIDField())
    records_completed = serializers.IntegerField(
        allow_null=True,
        help_text="Number of rows this run exported.",
    )


class RetrieveFailedOutputSerializer(serializers.Serializer):
    """Typed output for view set `retrieve` with any of the failed statuses."""

    status = serializers.ChoiceField(choices=["Failed", "FailedRetryable", "FailedBilling", "Terminated", "TimedOut"])
    error = serializers.CharField()


class RetrieveOutputSerializer(serializers.Serializer):
    """Retrieve serializer with all fields optional except status.

    The actual conditional shape is described by the polymorphic schema in
    @extend_schema. This serializer exists as a runtime/fallback type.
    """

    status = serializers.ChoiceField(choices=BatchExportRunStatus.choices)
    error = serializers.CharField(required=False)
    files = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
    )
    records_completed = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Number of rows this run exported.",
    )


class TooManyConcurrentFileDownloads(APIException):
    """Raised when a team creates too many file download batch exports."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "too_many_concurrent_file_downloads"
    default_detail = "Too many concurrent file download batch exports for this team."


def _to_file_download_request(validated_data: dict[str, Any]) -> contracts.FileDownloadRequest:
    file_config = validated_data["file"]
    include = validated_data.get("include")
    exclude = validated_data.get("exclude")
    return contracts.FileDownloadRequest(
        model=validated_data["model"],
        format=file_config["format"],
        compression=file_config["compression"],
        max_size_mb=file_config["max_size_mb"],
        data_interval_start=validated_data.get("data_interval_start"),
        data_interval_end=validated_data.get("data_interval_end"),
        include_events=tuple(include) if include is not None else None,
        exclude_events=tuple(exclude) if exclude is not None else None,
        hogql_query=validated_data.get("hogql_query"),
        hogql_modifiers=validated_data.get("hogql_modifiers"),
    )


@extend_schema(tags=["batch_exports"])
@extend_schema_view(logs=extend_schema(parameters=[RUN_ID_PARAMETER]))
class FileDownloadBatchExportOnDemandViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, viewsets.GenericViewSet):
    scope_object = "batch_export"
    serializer_class = FileDownloadBatchExportOnDemandSerializer
    log_source = "batch_exports"

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.action == "list":
            return ListOutputSerializer

        return FileDownloadBatchExportOnDemandSerializer

    def get_throttles(self) -> list[BaseThrottle]:
        # `count_rows` runs a ClickHouse query per request, so it needs tighter limits than
        # the default throttles.
        if self.action == "count_rows":
            return [BatchExportsCountRowsBurstRateThrottle(), BatchExportsCountRowsSustainedRateThrottle()]
        return super().get_throttles()

    def dangerously_get_object(self) -> contracts.FileDownloadRun:
        # The mixin's get_object() reads through a queryset, which this view does not have, so the
        # run is read through the facade instead. That skips the mixin's team filter and object
        # permission check, so both happen here: the facade filters by team, and
        # check_object_permissions runs on the contract. `logs` reads the run through here too.
        run_id = parse_path_uuid(self.kwargs["pk"])
        try:
            run = batch_exports_api.get_file_download_run(self.team_id, run_id)
        except contracts.FileDownloadNotFoundError as e:
            raise NotFound(*e.args) from e
        self.check_object_permissions(self.request, run)
        return run

    def list(self, request, *args, **kwargs) -> response.Response:
        # The facade slices the page, so the paginator gets its state set directly instead of a queryset.
        paginator = cast(LimitOffsetPagination, self.paginator)
        limit = paginator.get_limit(request)
        offset = paginator.get_offset(request)
        # PAGE_SIZE gives every request a limit.
        assert limit is not None
        runs, count = batch_exports_api.list_file_download_runs(self.team_id, offset=offset, limit=limit)
        paginator.request = request
        paginator.limit = limit
        paginator.offset = offset
        paginator.count = count
        return paginator.get_paginated_response(ListOutputSerializer(runs, many=True).data)

    @extend_schema(
        request=PolymorphicProxySerializer(
            component_name="CreateFileDownloadRequest",
            serializers={
                "events": FileDownloadEventsRequestSerializer,
                "persons": FileDownloadPersonsRequestSerializer,
                "sessions": FileDownloadSessionsRequestSerializer,
                "hogql": FileDownloadHogQLRequestSerializer,
            },
            resource_type_field_name="model",
        ),
        responses={202: CreateOutputSerializer},
    )
    def create(self, request, *args, **kwargs):
        """Create and start a batch export on demand run to download a file."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not isinstance(request.user, User):
            raise NotAuthenticated()

        try:
            run_id = batch_exports_api.start_file_download(
                self.team_id,
                user_id=request.user.pk,
                request=_to_file_download_request(serializer.validated_data),
            )
        except contracts.TooManyConcurrentFileDownloadsError as e:
            raise TooManyConcurrentFileDownloads() from e
        except contracts.FileDownloadStartError:
            return response.Response(
                {
                    "detail": "The batch export failed to start. Check our status page for any ongoing incidents and try again later."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return response.Response({"id": run_id}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        parameters=[RUN_ID_PARAMETER],
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
        """Get a batch export on demand run.

        If the underlying batch export run has completed, we return keys to the
        generated file downloads so that users may download them by making a request
        to /download.
        """
        run = self.get_object()

        body: dict[str, Any] = {"status": run.status}
        if run.files is not None:
            body["files"] = [str(file_id) for file_id in run.files]
            body["records_completed"] = run.records_completed
        if run.error is not None:
            body["error"] = run.error

        return response.Response(body)

    @extend_schema(parameters=[RUN_ID_PARAMETER])
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
        run = self.get_object()

        try:
            pre_signed_url = batch_exports_api.get_file_download_url(self.team_id, run.id, part)
        except contracts.InvalidFileDownloadRequestError as e:
            raise ValidationError(str(e)) from e
        except contracts.FileDownloadNotFoundError as e:
            raise NotFound(*e.args) from e

        response = HttpResponseRedirect(redirect_to=pre_signed_url)
        response["Cache-Control"] = "no-store"

        return response

    @extend_schema(request=None, parameters=[RUN_ID_PARAMETER])
    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def cancel(self, request, *args, **kwargs) -> response.Response:
        """Cancel an ongoing file-download batch export."""
        run = self.get_object()

        try:
            run_status = batch_exports_api.cancel_file_download(self.team_id, run.id)
        except contracts.InvalidFileDownloadRequestError as e:
            raise ValidationError(str(e)) from e
        except contracts.FileDownloadNotFoundError as e:
            raise NotFound(*e.args) from e

        return response.Response({"status": run_status})

    @action(
        methods=["POST"],
        detail=False,
        # User queries could impact production limits and billing. So, we
        # require write permissions despite being a "read" operation.
        required_scopes=["batch_export:write"],
        request=FileDownloadCountRowsRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=FileDownloadCountRowsResponseSerializer,
                description="Number of rows the export would produce if started now.",
            ),
            400: OpenApiResponse(
                description="The request or the HogQL query is invalid, or counting timed out because "
                "the query is too complex or the count is too large, which can mean the export would "
                "be very large."
            ),
            403: OpenApiResponse(description="HogQL batch exports are not enabled for this team."),
        },
    )
    @validated_request(request_serializer=FileDownloadCountRowsRequestSerializer)
    def count_rows(self, request: ValidatedRequest, *args, **kwargs) -> response.Response:
        """Count the rows a HogQL batch export would produce if started now."""
        if not isinstance(request.user, User):
            raise NotAuthenticated()
        check_hogql_batch_exports_enabled(self.team)

        try:
            count = batch_exports_api.count_hogql_rows(
                self.team_id,
                user_id=request.user.pk,
                hogql_query=request.validated_data["hogql_query"],
                hogql_modifiers=request.validated_data.get("hogql_modifiers"),
                data_interval_start=request.validated_data.get("data_interval_start"),
                data_interval_end=request.validated_data.get("data_interval_end"),
            )
        except contracts.UnsupportedHogQLQueryError as e:
            raise ValidationError({"hogql_query": str(e)}) from e
        except (ExposedHogQLError, ExposedCHQueryError) as e:
            raise ValidationError(str(e), getattr(e, "code_name", None)) from e
        except ClickHouseQueryTimeOut as e:
            # For a count, a timeout is feedback about the user's query, so report it as a 400
            # with guidance instead of the generic 504.
            raise ValidationError(COUNT_ROWS_TIMEOUT_MESSAGE, "timeout_exceeded") from e

        return response.Response({"count": count})
