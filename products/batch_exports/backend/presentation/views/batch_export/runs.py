"""Batch export run endpoints: list, retrieve, retry and cancel."""

import uuid
from typing import Any, cast

from django.utils.timezone import now

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import filters, mixins, request, response, serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError

from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.utils import relative_date_parse

from products.batch_exports.backend.facade import (
    api as batch_exports_api,
    contracts,
)
from products.batch_exports.backend.facade.enums import BatchExportRunStatus
from products.batch_exports.backend.presentation.views.batch_export.pagination import FacadeCursorPagination
from products.batch_exports.backend.presentation.views.utils import (
    BIG_INTEGER_MAX,
    BIG_INTEGER_MIN,
    INTEGER_MAX,
    INTEGER_MIN,
    parse_path_uuid,
)

# The viewset declares no queryset, so drf-spectacular cannot read the type of the ids from a model.
RUN_ID_PARAMETER = OpenApiParameter(
    "id", OpenApiTypes.UUID, OpenApiParameter.PATH, description="A UUID string identifying this batch export run."
)


class BatchExportRunSerializer(serializers.Serializer):
    """Serializer for a BatchExportRun model."""

    # TODO: Why aren't all these read only?
    id = serializers.UUIDField(read_only=True)
    # Underlying model can be null for on demand batch exports. But scheduled
    # batch exports always have a data_interval_end given by the schedule
    # itself (even if that isn't used by the underlying HogQL query). This
    # narrows the API contract so any consumers don't have to deal with
    # nullable data_interval_end.
    data_interval_end = serializers.DateTimeField(
        required=True, allow_null=False, help_text="The end of the data interval."
    )
    status = serializers.ChoiceField(choices=BatchExportRunStatus.choices, help_text="The status of this run.")
    records_completed = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=INTEGER_MIN,
        max_value=INTEGER_MAX,
        help_text="The number of records that have been exported.",
    )
    records_failed = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=INTEGER_MIN,
        max_value=INTEGER_MAX,
        help_text="The number of records that failed downstream processing (e.g. hog function execution errors).",
    )
    latest_error = serializers.CharField(
        required=False, allow_null=True, help_text="The latest error that occurred during this run."
    )
    data_interval_start = serializers.DateTimeField(
        required=False, allow_null=True, help_text="The start of the data interval."
    )
    cursor = serializers.CharField(
        required=False, allow_null=True, help_text="An opaque cursor that may be used to resume."
    )
    created_at = serializers.DateTimeField(
        read_only=True, help_text="The timestamp at which this BatchExportRun was created."
    )
    finished_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="The timestamp at which this BatchExportRun finished, successfully or not.",
    )
    last_updated_at = serializers.DateTimeField(
        read_only=True, help_text="The timestamp at which this BatchExportRun was last updated."
    )
    records_total_count = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=INTEGER_MIN,
        max_value=INTEGER_MAX,
        help_text="The total count of records that should be exported in this BatchExportRun.",
    )
    bytes_exported = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=BIG_INTEGER_MIN,
        max_value=BIG_INTEGER_MAX,
        help_text="The number of bytes that have been exported in this BatchExportRun.",
    )
    batch_export = serializers.UUIDField(
        source="batch_export_id",
        read_only=True,
        allow_null=True,
        help_text="The `BatchExport` this run belongs to.",
    )
    batch_export_on_demand = serializers.UUIDField(
        source="batch_export_on_demand_id",
        required=False,
        allow_null=True,
        help_text="The `BatchExportOnDemand` this run belongs to.",
    )
    backfill = serializers.UUIDField(
        source="backfill_id", required=False, allow_null=True, help_text="The backfill this run belongs to."
    )


class BatchExportRunListQuerySerializer(serializers.Serializer):
    """Query parameters accepted when listing the runs of a batch export."""

    status = serializers.ListField(
        required=False,
        child=serializers.ChoiceField(choices=BatchExportRunStatus.choices),
        help_text="Only return runs in these statuses. Repeat the parameter to pass more than one status.",
    )
    after = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Only return runs created at or after this point. "
            "Accepts an ISO-8601 datetime or a relative value like `-7d`. Defaults to `-7d`. "
            "Ignored when ordering by `data_interval_start`."
        ),
    )
    before = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Only return runs created at or before this point. "
            "Accepts an ISO-8601 datetime or a relative value like `-1d`. Defaults to now. "
            "Ignored when ordering by `data_interval_start`."
        ),
    )
    start = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Only return runs whose data interval starts at or after this point. "
            "Accepts an ISO-8601 datetime or a relative value like `-7d`. Defaults to `-7d`. "
            "Only applies when ordering by `data_interval_start`."
        ),
    )
    end = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Only return runs whose data interval ends at or before this point. "
            "Accepts an ISO-8601 datetime or a relative value like `-1d`. Defaults to now. "
            "Only applies when ordering by `data_interval_start`."
        ),
    )


class RunsCursorPagination(FacadeCursorPagination):
    page_size = 100


@extend_schema(
    tags=["batch_exports"],
    parameters=[
        OpenApiParameter(
            "batch_export_id",
            {"type": "string", "format": "uuid", "description": "The `BatchExport` this run belongs to."},
            OpenApiParameter.PATH,
        )
    ],
)
@extend_schema_view(
    list=extend_schema(parameters=[BatchExportRunListQuerySerializer]),
    retrieve=extend_schema(parameters=[RUN_ID_PARAMETER]),
    logs=extend_schema(parameters=[RUN_ID_PARAMETER]),
)
class BatchExportRunViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    scope_object = "batch_export"
    serializer_class = BatchExportRunSerializer
    pagination_class = RunsCursorPagination
    # The paginator reads the ordering through this filter, and the facade applies it.
    filter_backends = [filters.OrderingFilter]
    ordering_fields = list(contracts.BATCH_EXPORT_RUN_ORDERING_FIELDS)
    ordering = "-created_at"
    log_source = "batch_exports"

    def get_log_entry_instance_id(self) -> str:
        return cast(str, self.parents_query_dict["run_id"])

    def _get_export_id(self) -> uuid.UUID:
        return parse_path_uuid(self.kwargs["parent_lookup_batch_export_id"])

    def _get_run_filters(self) -> contracts.BatchExportRunFilters:
        query = BatchExportRunListQuerySerializer(data=self.request.GET)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        after = params.get("after")
        before = params.get("before")
        start = params.get("start")
        end = params.get("end")
        statuses = tuple(params.get("status") or ())

        # OrderingFilter applies the sort and declares this parameter, so it is not on the serializer.
        ordering = self.request.GET.get("ordering", None)
        # If we're ordering by data_interval_start, we need to filter by that otherwise we're ordering by created_at
        if ordering == "data_interval_start" or ordering == "-data_interval_start":
            start_timestamp = relative_date_parse(start if start else "-7d", self.team.timezone_info)
            end_timestamp = relative_date_parse(end, self.team.timezone_info) if end else now()
            return contracts.BatchExportRunFilters(
                statuses=statuses, data_interval=contracts.DatetimeRange(start=start_timestamp, end=end_timestamp)
            )

        after_datetime = relative_date_parse(after if after else "-7d", self.team.timezone_info)
        before_datetime = relative_date_parse(before, self.team.timezone_info) if before else now()
        return contracts.BatchExportRunFilters(
            statuses=statuses, created=contracts.DatetimeRange(start=after_datetime, end=before_datetime)
        )

    def dangerously_get_object(self) -> contracts.BatchExportRunDetail:
        # The mixin's get_object() reads through a queryset, which this view no longer has, so the
        # run is read through the facade instead. That skips the mixin's team filter and object
        # permission check, so both happen here: the facade filters by team and export, and
        # check_object_permissions runs on the contract. `logs` reads the run through here too.
        # Like the list, a lookup only finds a run that matches the list filters.
        try:
            run = batch_exports_api.get_batch_export_run(
                self.team_id, self._get_export_id(), parse_path_uuid(self.kwargs["pk"]), filters=self._get_run_filters()
            )
        except contracts.BatchExportRunNotFoundError as e:
            raise NotFound(*e.args) from e
        self.check_object_permissions(self.request, run)
        return run

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        export_id = self._get_export_id()
        filters = self._get_run_filters()
        return cast(FacadeCursorPagination, self.paginator).get_paginated_facade_response(
            request,
            self,
            lambda page: batch_exports_api.list_batch_export_runs(self.team_id, export_id, filters=filters, page=page),
        )

    @extend_schema(parameters=[RUN_ID_PARAMETER])
    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def retry(self, *args, **kwargs) -> response.Response:
        """Retry a batch export run.

        We use the same underlying mechanism as when backfilling a batch export, as retrying
        a run is the same as backfilling one run.
        """
        run = self.get_object()

        try:
            backfill_id = batch_exports_api.retry_batch_export_run(
                self.team_id, self._get_export_id(), run.id, filters=self._get_run_filters()
            )
        except contracts.BatchExportRunNotFoundError as e:
            raise NotFound(*e.args) from e

        return response.Response({"backfill_id": backfill_id}, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[RUN_ID_PARAMETER])
    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def cancel(self, *args, **kwargs) -> response.Response:
        """Cancel a batch export run."""
        run = self.get_object()

        try:
            batch_exports_api.cancel_batch_export_run(
                self.team_id, self._get_export_id(), run.id, filters=self._get_run_filters()
            )
        except contracts.InvalidBatchExportRunRequestError as e:
            raise ValidationError(str(e)) from e
        except contracts.BatchExportRunNotFoundError as e:
            raise NotFound(*e.args) from e

        return response.Response({"cancelled": True})
