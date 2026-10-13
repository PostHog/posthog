"""Batch export run endpoints: list, retrieve, retry and cancel."""

from typing import cast

from django.utils.timezone import now

import structlog
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, response, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination

from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.temporal.common.client import sync_connect
from posthog.utils import relative_date_parse

from products.batch_exports.backend.models.batch_export import BatchExportRun
from products.batch_exports.backend.service import backfill_export, cancel_running_batch_export_run

logger = structlog.get_logger(__name__)


class BatchExportRunSerializer(serializers.ModelSerializer):
    """Serializer for a BatchExportRun model."""

    # Underlying model can be null for on demand batch exports. But scheduled
    # batch exports always have a data_interval_end given by the schedule
    # itself (even if that isn't used by the underlying HogQL query). This
    # narrows the API contract so any consumers don't have to deal with
    # nullable data_interval_end.
    data_interval_end = serializers.DateTimeField(
        required=True, allow_null=False, help_text="The end of the data interval."
    )

    class Meta:
        model = BatchExportRun
        fields = "__all__"
        # TODO: Why aren't all these read only?
        read_only_fields = ["batch_export"]


class BatchExportRunListQuerySerializer(serializers.Serializer):
    """Query parameters accepted when listing the runs of a batch export."""

    status = serializers.ListField(
        required=False,
        child=serializers.ChoiceField(choices=BatchExportRun.Status.choices),
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


class RunsCursorPagination(CursorPagination):
    page_size = 100


@extend_schema(tags=["batch_exports"])
@extend_schema_view(list=extend_schema(parameters=[BatchExportRunListQuerySerializer]))
class BatchExportRunViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "batch_export"
    queryset = BatchExportRun.objects.select_related("batch_export__destination").all()
    serializer_class = BatchExportRunSerializer
    pagination_class = RunsCursorPagination
    filter_rewrite_rules = {"team_id": "batch_export__team_id"}
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "data_interval_start"]
    ordering = "-created_at"
    log_source = "batch_exports"

    def get_log_entry_instance_id(self) -> str:
        return cast(str, self.parents_query_dict["run_id"])

    def safely_get_queryset(self, queryset):
        query = BatchExportRunListQuerySerializer(data=self.request.GET)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        after = params.get("after")
        before = params.get("before")
        start = params.get("start")
        end = params.get("end")

        # OrderingFilter applies the sort and declares this parameter, so it is not on the serializer.
        ordering = self.request.GET.get("ordering", None)
        # If we're ordering by data_interval_start, we need to filter by that otherwise we're ordering by created_at
        if ordering == "data_interval_start" or ordering == "-data_interval_start":
            start_timestamp = relative_date_parse(start if start else "-7d", self.team.timezone_info)
            end_timestamp = relative_date_parse(end, self.team.timezone_info) if end else now()
            queryset = queryset.filter(data_interval_start__gte=start_timestamp, data_interval_end__lte=end_timestamp)
        else:
            after_datetime = relative_date_parse(after if after else "-7d", self.team.timezone_info)
            before_datetime = relative_date_parse(before, self.team.timezone_info) if before else now()
            date_range = (after_datetime, before_datetime)
            queryset = queryset.filter(created_at__range=date_range)

        if statuses := params.get("status"):
            queryset = queryset.filter(status__in=statuses)

        queryset = queryset.filter(batch_export_id=self.kwargs["parent_lookup_batch_export_id"])
        return queryset

    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def retry(self, *args, **kwargs) -> response.Response:
        """Retry a batch export run.

        We use the same underlying mechanism as when backfilling a batch export, as retrying
        a run is the same as backfilling one run.
        """
        batch_export_run = self.get_object()

        temporal = sync_connect()
        backfill_id = backfill_export(
            temporal,
            str(batch_export_run.batch_export.id),
            self.team_id,
            batch_export_run.data_interval_start,
            batch_export_run.data_interval_end,
        )

        return response.Response({"backfill_id": backfill_id}, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def cancel(self, *args, **kwargs) -> response.Response:
        """Cancel a batch export run."""

        batch_export_run: BatchExportRun = self.get_object()

        if (
            batch_export_run.status == BatchExportRun.Status.RUNNING
            or batch_export_run.status == BatchExportRun.Status.STARTING
        ):
            temporal = sync_connect()
            try:
                cancel_running_batch_export_run(temporal, batch_export_run)
            except Exception as e:
                # It could be the case that the run is already cancelled but our database hasn't been updated yet. In
                # this case, we can just ignore the error but log it for visibility (in case there is an actual issue).
                logger.warning("Error cancelling batch export run: %s", e)
        else:
            raise ValidationError(f"Cannot cancel a run that is in '{batch_export_run.status}' status")

        return response.Response({"cancelled": True})
