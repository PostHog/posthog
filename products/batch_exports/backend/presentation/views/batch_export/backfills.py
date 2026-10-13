"""Batch export backfill endpoints: create, list, retrieve and cancel."""

import uuid
import datetime as dt
from dataclasses import dataclass
from typing import Any

from django.conf import settings

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema_field
from rest_framework import filters, mixins, request, response, serializers, status, viewsets
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.pagination import CursorPagination

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import groups
from posthog.models import Team, User
from posthog.temporal.common.client import sync_connect

from products.batch_exports.backend.hogql_source import (
    DATA_INTERVAL_START_PLACEHOLDER,
    UnsupportedHogQLQueryError,
    find_interval_placeholders,
    parse_hogql_select_for_batch_export,
)
from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportBackfill
from products.batch_exports.backend.service import (
    BatchExportWithNoEndNotAllowedError,
    backfill_export,
    sync_cancel_running_batch_export_backfill,
)

logger = structlog.get_logger(__name__)


def validate_date_input(date_input: Any, batch_export: BatchExport) -> dt.datetime:
    """Validate and parse a date/datetime input as a proper dt.datetime.

    If the interval is daily or weekly, we expect the input to be an ISO formatted date string.
    We then need to convert it to a datetime using the batch export's timezone and offset.

    For all other intervals, we expect the input to be an ISO formatted datetime string.

    Args:
        date_input: The datetime input to parse.

    Raises:
        ValidationError: If the input cannot be parsed.

    Returns:
        The parsed dt.datetime.
    """
    if batch_export.interval == "day" or batch_export.interval == "week":
        try:
            parsed_date = dt.date.fromisoformat(date_input)
        except (TypeError, ValueError):
            # Try to parse as a datetime string so we can give a more helpful error message
            try:
                parsed = dt.datetime.fromisoformat(date_input)
                raise ValidationError(
                    f"Input '{date_input}' is not a valid ISO formatted date. "
                    "Daily or weekly batch export backfills expect only the date component, but a time was included."
                )
            except (TypeError, ValueError):
                pass
            raise ValidationError(f"Input '{date_input}' is not a valid ISO formatted date.")

        if batch_export.interval == "week":
            # Validate that the provided date is on the correct day of the week, according to the batch export's day offset
            # Python's date.isoweekday() returns 1-7 for Monday-Sunday, so we need to convert it to 0-6 for Sunday-Saturday
            normalized_day = parsed_date.isoweekday() % 7
            if normalized_day != batch_export.offset_day:
                # get day of week as string
                day_of_week = parsed_date.strftime("%A")
                expected_day_of_week = batch_export.offset_day_name
                assert expected_day_of_week is not None
                raise ValidationError(
                    f"Input {date_input} is not on the correct day of the week for this batch export. "
                    f"{date_input} is a {day_of_week} but this batch export is configured to run "
                    f"weekly on {expected_day_of_week}."
                )

        # If we have an offset hour, add it to the parsed datetime
        # Also, apply the timezone to the parsed datetime
        time_of_day = dt.time.min if batch_export.offset_hour is None else dt.time(hour=batch_export.offset_hour)
        parsed = dt.datetime.combine(parsed_date, time_of_day).replace(tzinfo=batch_export.timezone_info)

    else:
        try:
            parsed = dt.datetime.fromisoformat(date_input)
        except (TypeError, ValueError):
            raise ValidationError(f"Input {date_input} is not a valid ISO formatted datetime.")

        if parsed.tzinfo is None:
            raise ValidationError(f"Input {date_input} is naive.")

    return parsed


@dataclass(frozen=False)
class BatchExportBackfillProgress:
    """Progress information for a batch export backfill."""

    total_runs: int | None
    finished_runs: int | None
    progress: float | None


class BatchExportBackfillSerializer(serializers.ModelSerializer):
    progress = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = BatchExportBackfill
        fields = "__all__"

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "total_runs": {"type": "integer", "nullable": True},
                "finished_runs": {"type": "integer", "nullable": True},
                "progress": {"type": "number", "nullable": True},
            },
        }
    )
    def get_progress(self, obj: BatchExportBackfill) -> BatchExportBackfillProgress | None:
        """Return progress information containing total runs, finished runs, and progress percentage.

        To reduce the number of database calls we make (which could be expensive when fetching a list of backfills) we
        only get the list of completed runs from the DB if the backfill is still running.
        """
        if obj.status == obj.Status.COMPLETED:
            return BatchExportBackfillProgress(
                total_runs=obj.total_expected_runs, finished_runs=obj.total_expected_runs, progress=1.0
            )
        elif obj.status not in (obj.Status.RUNNING, obj.Status.STARTING):
            # if backfill finished in some other state then progress info may not be meaningful
            return None

        total_runs = obj.total_expected_runs
        if not total_runs:
            return None

        if obj.start_at is None and obj.adjusted_start_at is None:
            # if it's just a single run, backfilling from the beginning of time, we can't calculate progress based on
            # the number of completed runs so better to return None
            return None

        finished_runs = obj.get_finished_runs()
        # just make sure we never return a progress > 1
        total_runs = max(total_runs, finished_runs)
        return BatchExportBackfillProgress(
            total_runs=total_runs, finished_runs=finished_runs, progress=round(finished_runs / total_runs, ndigits=1)
        )


class BackfillsCursorPagination(CursorPagination):
    page_size = 50


class TooManyConcurrentBackfills(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "too_many_concurrent_backfills"
    default_detail = "Too many concurrent batch export backfills for this team."


def create_backfill(
    team: Team,
    batch_export: BatchExport,
    start_at_input: str | None,
    end_at_input: str | None,
) -> str:
    """Create a new backfill for a BatchExport.

    Args:
        team: The team creating the backfill
        batch_export: The batch export to backfill
        start_at_input: ISO formatted datetime string for backfill start
        end_at_input: ISO formatted datetime string for backfill end

    Returns:
        The pre-generated backfill ID.
    """
    # Currently, backfills from the beginning of time usually fail due to us hitting ClickHouse memory limits.
    # Therefore, this feature is behind a feature flag while we improve backfilling behavior.
    if start_at_input is None:
        if not posthoganalytics.feature_enabled(
            "batch-export-earliest-backfill",
            str(team.uuid),
            groups={"organization": str(team.organization.id)},
            group_properties={
                "organization": {
                    "id": str(team.organization.id),
                    "created_at": team.organization.created_at,
                }
            },
            send_feature_flag_events=False,
        ):
            raise ValidationError("Backfilling from the beginning of time is not enabled for this team.")

        if batch_export.model == BatchExport.Model.HOGQL and (hogql_query := batch_export.hogql_query) is not None:
            try:
                parsed = parse_hogql_select_for_batch_export(hogql_query)
            except UnsupportedHogQLQueryError as e:
                raise ValidationError(str(e)) from e
            if DATA_INTERVAL_START_PLACEHOLDER in find_interval_placeholders(parsed):
                # TODO: We should maybe support beginning-of-time backfills with this placeholder.
                raise ValidationError(
                    "This query references {data_interval_start}, which is unavailable when backfilling from the "
                    "beginning of time. Provide 'start_at' or remove {data_interval_start} from the query."
                )

    concurrency_limit = settings.BATCH_EXPORT_MAX_CONCURRENT_BACKFILLS_PER_TEAM
    active_backfills = BatchExportBackfill.objects.filter(
        team_id=team.pk,
        status__in=[
            BatchExportBackfill.Status.STARTING,
            BatchExportBackfill.Status.RUNNING,
        ],
    ).count()
    if active_backfills >= concurrency_limit:
        raise TooManyConcurrentBackfills(
            f"This team already has {concurrency_limit} batch export backfills running. "
            f"Wait for some to finish or cancel them before creating more."
        )

    temporal = sync_connect()

    if start_at_input is not None:
        start_at = validate_date_input(start_at_input, batch_export)
    else:
        start_at = None

    if end_at_input is not None:
        end_at = validate_date_input(end_at_input, batch_export)
    else:
        end_at = None

    # Note: earliest backfill date validation and adjustment is now done in the Temporal workflow
    # via the get_backfill_info activity. This allows the potentially slow ClickHouse query to run
    # asynchronously rather than blocking the HTTP request.

    backfill_id = str(uuid.uuid4())

    if start_at is None or end_at is None:
        backfill_export(
            temporal=temporal,
            batch_export_id=str(batch_export.pk),
            team_id=team.pk,
            start_at=start_at,
            end_at=end_at,
            backfill_id=backfill_id,
        )
        return backfill_id

    if start_at >= end_at:
        raise ValidationError("The initial backfill datetime 'start_at' must be before 'end_at'")
    if end_at > dt.datetime.now(dt.UTC):
        raise ValidationError(f"The provided 'end_at' ({end_at.isoformat()}) is in the future")

    try:
        backfill_export(
            temporal=temporal,
            batch_export_id=str(batch_export.pk),
            team_id=team.pk,
            start_at=start_at,
            end_at=end_at,
            backfill_id=backfill_id,
        )
        return backfill_id
    except BatchExportWithNoEndNotAllowedError:
        raise ValidationError("Backfilling a BatchExport with no end date is not allowed")


class BatchExportBackfillViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """ViewSet for BatchExportBackfill models.

    Allows creating and reading backfills, but not updating or deleting them.
    """

    scope_object = "batch_export"
    queryset = BatchExportBackfill.objects.all()
    serializer_class = BatchExportBackfillSerializer
    pagination_class = BackfillsCursorPagination
    filter_rewrite_rules = {"team_id": "batch_export__team_id"}
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "start_at"]
    ordering = "-created_at"

    def safely_get_queryset(self, queryset):
        return queryset.filter(batch_export_id=self.kwargs["parent_lookup_batch_export_id"])

    def create(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Create a new backfill for a BatchExport."""
        try:
            batch_export = BatchExport.objects.select_related("destination").get(
                id=self.kwargs["parent_lookup_batch_export_id"], team_id=self.team_id
            )
        except BatchExport.DoesNotExist:
            raise NotFound("BatchExport not found.")

        start_at = request.data.get("start_at")
        end_at = request.data.get("end_at")

        backfill_id = create_backfill(
            self.team,
            batch_export,
            start_at,
            end_at,
        )

        if isinstance(request.user, User):
            try:
                posthoganalytics.capture(
                    distinct_id=str(request.user.distinct_id),
                    event="batch export backfill created",
                    properties={
                        "backfill_id": backfill_id,
                        "batch_export_id": str(batch_export.pk),
                        "destination_type": batch_export.destination.type,
                        "has_start_at": start_at is not None,
                        "has_end_at": end_at is not None,
                        "team_id": self.team_id,
                    },
                    groups=groups(self.team.organization, self.team),
                )
            except Exception:
                logger.exception("Failed to capture batch export backfill created event")

        return response.Response({"backfill_id": backfill_id}, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def cancel(self, *args, **kwargs) -> response.Response:
        """Cancel a batch export backfill."""

        batch_export_backfill: BatchExportBackfill = self.get_object()

        if (
            batch_export_backfill.status == BatchExportBackfill.Status.RUNNING
            or batch_export_backfill.status == BatchExportBackfill.Status.STARTING
        ):
            temporal = sync_connect()
            try:
                sync_cancel_running_batch_export_backfill(temporal, batch_export_backfill)
            except Exception as e:
                # It could be the case that the backfill is already cancelled but our database hasn't been updated yet.
                # In this case, we can just ignore the error but log it for visibility (in case there is an actual
                # issue).
                logger.warning("Error cancelling batch export backfill: %s", e)
        else:
            raise ValidationError(f"Cannot cancel a backfill that is in '{batch_export_backfill.status}' status")

        return response.Response({"cancelled": True})
