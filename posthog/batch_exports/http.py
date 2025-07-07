import datetime as dt
from dataclasses import dataclass
from typing import Any, TypedDict, cast

import posthoganalytics
import structlog
from django.db import transaction
from django.utils.timezone import now
from loginas.utils import is_impersonated_session
from rest_framework import (
    filters,
    mixins,
    request,
    response,
    serializers,
    status,
    viewsets,
)
from rest_framework.exceptions import (
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.pagination import CursorPagination

from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.batch_exports.models import BATCH_EXPORT_INTERVALS
from posthog.batch_exports.service import (
    BatchExportIdError,
    BatchExportSchema,
    BatchExportServiceError,
    BatchExportServiceRPCError,
    BatchExportWithNoEndNotAllowedError,
    backfill_export,
    cancel_running_batch_export_run,
    disable_and_delete_export,
    fetch_earliest_backfill_start_at,
    pause_batch_export,
    sync_batch_export,
    sync_cancel_running_batch_export_backfill,
    unpause_batch_export,
)
from posthog.constants import AvailableFeature
from posthog.hogql import ast, errors
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.models import (
    BatchExport,
    BatchExportBackfill,
    BatchExportDestination,
    BatchExportRun,
    Team,
    User,
)
from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode
from posthog.temporal.batch_exports.destination_tests import get_destination_test
from posthog.temporal.batch_exports.s3_batch_export import SUPPORTED_COMPRESSIONS
from posthog.temporal.common.client import sync_connect
from posthog.utils import relative_date_parse

logger = structlog.get_logger(__name__)


def validate_date_input(date_input: Any, team: Team | None = None) -> dt.datetime:
    """Parse any datetime input as a proper dt.datetime.

    Args:
        date_input: The datetime input to parse.

    Raises:
        ValidationError: If the input cannot be parsed.

    Returns:
        The parsed dt.datetime.
    """
    try:
        # The Right Way (TM) to check this would be by calling isinstance, but that doesn't feel very Pythonic.
        # As far as I'm concerned, if you give me something that quacks like an isoformatted str, you are golden.
        # Read more here: https://github.com/python/mypy/issues/2420.
        # Once PostHog is 3.11, try/except is zero cost if nothing is raised: https://bugs.python.org/issue40222.
        parsed = dt.datetime.fromisoformat(date_input)
    except (TypeError, ValueError):
        raise ValidationError(f"Input {date_input} is not a valid ISO formatted datetime.")

    if parsed.tzinfo is None:
        raise ValidationError(f"Input {date_input} is naive.")

    else:
        if team is not None:
            parsed = parsed.astimezone(team.timezone_info)

    return parsed


class BatchExportRunSerializer(serializers.ModelSerializer):
    """Serializer for a BatchExportRun model."""

    class Meta:
        model = BatchExportRun
        fields = "__all__"
        # TODO: Why aren't all these read only?
        read_only_fields = ["batch_export"]


class RunsCursorPagination(CursorPagination):
    page_size = 100


class BatchExportRunViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "batch_export"
    queryset = BatchExportRun.objects.all()
    serializer_class = BatchExportRunSerializer
    pagination_class = RunsCursorPagination
    filter_rewrite_rules = {"team_id": "batch_export__team_id"}
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "data_interval_start"]
    ordering = "-created_at"
    log_source = "batch_exports"

    def get_log_entry_instance_id(self) -> str:
        return self.parents_query_dict.get("run_id", None)

    def safely_get_queryset(self, queryset):
        after = self.request.GET.get("after", None)
        before = self.request.GET.get("before", None)
        start = self.request.GET.get("start", None)
        end = self.request.GET.get("end", None)
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
        backfill_workflow_id = backfill_export(
            temporal,
            str(batch_export_run.batch_export.id),
            self.team_id,
            batch_export_run.data_interval_start,
            batch_export_run.data_interval_end,
        )

        return response.Response({"backfill_id": backfill_workflow_id})

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


class BatchExportDestinationSerializer(serializers.ModelSerializer):
    """Serializer for an BatchExportDestination model."""

    class Meta:
        model = BatchExportDestination
        fields = ["type", "config"]

    def create(self, validated_data: dict) -> BatchExportDestination:
        """Create a BatchExportDestination."""
        export_destination = BatchExportDestination.objects.create(**validated_data)
        return export_destination

    def to_representation(self, instance: BatchExportDestination) -> dict:
        data = super().to_representation(instance)
        data["config"] = {
            k: v for k, v in data["config"].items() if k not in BatchExportDestination.secret_fields[instance.type]
        }
        return data


class HogQLSelectQueryField(serializers.Field):
    def to_internal_value(self, data: str) -> ast.SelectQuery | ast.SelectSetQuery:
        """Parse a HogQL SelectQuery from a string query."""
        try:
            parsed_query = parse_select(data)
        except Exception:
            raise serializers.ValidationError("Failed to parse query")

        try:
            prepared_select_query: ast.SelectQuery = cast(
                ast.SelectQuery,
                prepare_ast_for_printing(
                    parsed_query,
                    context=HogQLContext(
                        team_id=self.context["team_id"],
                        enable_select_queries=True,
                        modifiers=HogQLQueryModifiers(
                            personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
                        ),
                    ),
                    dialect="clickhouse",
                ),
            )
        except errors.ExposedHogQLError as e:
            raise serializers.ValidationError(f"Invalid HogQL query: {e}")

        return prepared_select_query


class BatchExportsField(TypedDict):
    expression: str
    alias: str


class BatchExportsSchema(TypedDict):
    fields: list[BatchExportsField]
    values: dict[str, str]
    hogql_query: str


class BatchExportSerializer(serializers.ModelSerializer):
    """Serializer for a BatchExport model."""

    destination = BatchExportDestinationSerializer()
    latest_runs = BatchExportRunSerializer(many=True, read_only=True)
    interval = serializers.ChoiceField(choices=BATCH_EXPORT_INTERVALS)
    hogql_query = HogQLSelectQueryField(required=False)

    class Meta:
        model = BatchExport
        fields = [
            "id",
            "team_id",
            "name",
            "model",
            "destination",
            "interval",
            "paused",
            "created_at",
            "last_updated_at",
            "last_paused_at",
            "start_at",
            "end_at",
            "latest_runs",
            "hogql_query",
            "schema",
            "filters",
        ]
        read_only_fields = ["id", "team_id", "created_at", "last_updated_at", "latest_runs", "schema"]

    def validate(self, attrs: dict) -> dict:
        team = self.context["get_team"]()
        attrs["team"] = team

        has_addon = team.organization.is_feature_available(AvailableFeature.DATA_PIPELINES)

        if not has_addon:
            # Check if the user is impersonated - if so we allow changes as it could be an admin user fixing things

            if not is_impersonated_session(self.context["request"]):
                raise serializers.ValidationError("The Data Pipelines addon is required for batch exports.")

        return attrs

    def validate_destination(self, destination_attrs: dict):
        destination_type = destination_attrs["type"]
        if destination_type == BatchExportDestination.Destination.SNOWFLAKE:
            config = destination_attrs["config"]
            # for updates, get the existing config
            self.instance: BatchExport | None
            view = self.context.get("view")

            if self.instance is not None:
                existing_config = self.instance.destination.config
            elif view is not None and "pk" in view.kwargs:
                # Running validation for a `detail=True` action.
                instance = view.get_object()
                existing_config = instance.destination.config
            else:
                existing_config = {}
            merged_config = {**existing_config, **config}

            if config.get("authentication_type") == "password" and merged_config.get("password") is None:
                raise serializers.ValidationError("Password is required if authentication type is password")
            if config.get("authentication_type") == "keypair" and merged_config.get("private_key") is None:
                raise serializers.ValidationError("Private key is required if authentication type is key pair")
        if destination_attrs["type"] == BatchExportDestination.Destination.S3:
            config = destination_attrs["config"]
            # JSONLines is the default file format for S3 exports for legacy reasons
            file_format = config.get("file_format", "JSONLines")
            supported_file_formats = SUPPORTED_COMPRESSIONS.keys()
            if file_format not in supported_file_formats:
                raise serializers.ValidationError(
                    f"File format {file_format} is not supported. Supported file formats are {list(supported_file_formats)}"
                )
            compression = config.get("compression", None)
            if compression and compression not in SUPPORTED_COMPRESSIONS[file_format]:
                raise serializers.ValidationError(
                    f"Compression {compression} is not supported for file format {file_format}. Supported compressions are {SUPPORTED_COMPRESSIONS[file_format]}"
                )
        return destination_attrs

    def create(self, validated_data: dict) -> BatchExport:
        """Create a BatchExport."""
        destination_data = validated_data.pop("destination")
        team_id = self.context["team_id"]

        if validated_data["interval"] not in ("hour", "day", "week"):
            team = Team.objects.get(id=team_id)

            if not posthoganalytics.feature_enabled(
                "high-frequency-batch-exports",
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
                raise PermissionDenied("Higher frequency batch exports are not enabled for this team.")

        if validated_data.get("model", "events") == "sessions":
            team = Team.objects.get(id=team_id)

            if not posthoganalytics.feature_enabled(
                "sessions-batch-exports",
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
                raise PermissionDenied("Sessions batch exports are not enabled for this team.")

        hogql_query = None
        if hogql_query := validated_data.pop("hogql_query", None):
            batch_export_schema = self.serialize_hogql_query_to_batch_export_schema(hogql_query)
            validated_data["schema"] = batch_export_schema

        destination = BatchExportDestination(**destination_data)
        batch_export = BatchExport(team_id=team_id, destination=destination, **validated_data)
        sync_batch_export(batch_export, created=True)

        with transaction.atomic():
            destination.save()
            batch_export.save()

        return batch_export

    def serialize_hogql_query_to_batch_export_schema(self, hogql_query: ast.SelectQuery) -> BatchExportSchema:
        """Return a batch export schema from a HogQL query ast."""
        try:
            # Print the query in ClickHouse dialect to catch unresolved field errors, and discard the result
            context = HogQLContext(
                team_id=self.context["team_id"],
                enable_select_queries=True,
                limit_top_select=False,
                modifiers=HogQLQueryModifiers(
                    personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
                ),
            )
            print_prepared_ast(hogql_query, context=context, dialect="clickhouse")

            # Recreate the context
            context = HogQLContext(
                team_id=self.context["team_id"],
                enable_select_queries=True,
                limit_top_select=False,
            )
            batch_export_schema: BatchExportsSchema = {
                "fields": [],
                "values": {},
                "hogql_query": print_prepared_ast(hogql_query, context=context, dialect="hogql"),
            }
        except errors.ExposedHogQLError:
            raise serializers.ValidationError("Unsupported HogQL query")

        for field in hogql_query.select:
            expression = print_prepared_ast(
                field.expr,  # type: ignore
                context=context,
                dialect="clickhouse",
            )

            if isinstance(field, ast.Alias):
                alias = field.alias
            else:
                alias = expression

            batch_export_field: BatchExportsField = {
                "expression": expression,
                "alias": alias,
            }
            batch_export_schema["fields"].append(batch_export_field)

        batch_export_schema["values"] = context.values

        return batch_export_schema

    def validate_hogql_query(self, hogql_query: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery:
        """Validate a HogQLQuery being used for batch exports.

        This method essentially checks that a query is supported by batch exports:
        1. UNION ALL is not supported.
        2. Any JOINs are not supported.
        3. Query must SELECT FROM events, and only from events.
        """

        if isinstance(hogql_query, ast.SelectSetQuery):
            raise serializers.ValidationError("UNIONs are not supported")

        parsed = cast(ast.SelectQuery, hogql_query)

        if parsed.select_from is None:
            raise serializers.ValidationError("Query must SELECT FROM events")

        # Not sure how to make mypy understand this works, hence the ignore comment.
        # And if it doesn't, it's still okay as it could mean an unsupported query.
        # We would come back with the example to properly type this.
        if parsed.select_from.table.chain != ["events"]:  # type: ignore
            raise serializers.ValidationError("Query must only SELECT FROM events")

        if parsed.select_from.next_join is not None:
            raise serializers.ValidationError("JOINs are not supported")

        return hogql_query

    def update(self, batch_export: BatchExport, validated_data: dict) -> BatchExport:
        """Update a BatchExport."""
        destination_data = validated_data.pop("destination", None)

        with transaction.atomic():
            if destination_data:
                batch_export.destination.type = destination_data.get("type", batch_export.destination.type)
                batch_export.destination.config = {
                    **batch_export.destination.config,
                    **destination_data.get("config", {}),
                }

            if hogql_query := validated_data.pop("hogql_query", None):
                batch_export_schema = self.serialize_hogql_query_to_batch_export_schema(hogql_query)
                validated_data["schema"] = batch_export_schema

            batch_export.destination.save()
            batch_export = super().update(batch_export, validated_data)

            sync_batch_export(batch_export, created=False)

        return batch_export


class BatchExportViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, viewsets.ModelViewSet):
    scope_object = "batch_export"
    queryset = BatchExport.objects.exclude(deleted=True).order_by("-created_at").prefetch_related("destination").all()
    serializer_class = BatchExportSerializer
    log_source = "batch_exports"

    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def pause(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Pause a BatchExport."""
        if not isinstance(request.user, User):
            raise NotAuthenticated()

        batch_export = self.get_object()
        user_id = request.user.distinct_id
        team_id = batch_export.team_id
        note = f"Pause requested by user {user_id} from team {team_id}"

        temporal = sync_connect()

        try:
            pause_batch_export(temporal, str(batch_export.id), note=note)
        except BatchExportIdError:
            raise NotFound(f"BatchExport ID '{str(batch_export.id)}' not found.")
        except BatchExportServiceRPCError:
            raise ValidationError("Invalid request to pause a BatchExport could not be carried out")
        except BatchExportServiceError:
            raise

        return response.Response({"paused": True})

    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def unpause(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Unpause a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id
        note = f"Unpause requested by user {user_id} from team {team_id}"
        backfill = request.data.get("backfill", False)

        batch_export = self.get_object()
        temporal = sync_connect()

        try:
            unpause_batch_export(temporal, str(batch_export.id), note=note, backfill=backfill)
        except BatchExportIdError:
            raise NotFound(f"BatchExport ID '{str(batch_export.id)}' not found.")
        except BatchExportServiceRPCError:
            raise ValidationError("Invalid request to unpause a BatchExport could not be carried out")
        except BatchExportServiceError:
            raise

        return response.Response({"paused": False})

    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def backfill(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Trigger a backfill for a BatchExport.

        Note: This endpoint is deprecated. Please use POST /batch_exports/<id>/backfills/ instead.
        """
        batch_export = self.get_object()
        backfill_workflow_id = create_backfill(
            self.team,
            batch_export,
            request.data.get("start_at"),
            request.data.get("end_at"),
        )
        return response.Response({"backfill_id": backfill_workflow_id})

    def perform_destroy(self, instance: BatchExport):
        """Perform a BatchExport destroy by clearing Temporal and Django state.

        If the underlying Temporal Schedule doesn't exist, we ignore the error and proceed with the delete anyways.
        The Schedule could have been manually deleted causing Django and Temporal to go out of sync. For whatever reason,
        since we are deleting, we assume that we can recover from this state by finishing the delete operation by calling
        instance.save().
        """
        disable_and_delete_export(instance)

    @action(methods=["GET"], detail=False, required_scopes=["INTERNAL"])
    def test(self, request: request.Request, *args, **kwargs) -> response.Response:
        destination = request.query_params.get("destination", None)
        if not destination:
            return response.Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            destination_test = get_destination_test(destination=destination)
        except ValueError:
            return response.Response(status=status.HTTP_404_NOT_FOUND)

        return response.Response(destination_test.as_dict())

    @action(methods=["POST"], detail=False, required_scopes=["INTERNAL"])
    def run_test_step_new(self, request: request.Request, *args, **kwargs) -> response.Response:
        test_step = request.data.pop("step", 0)

        serializer = self.get_serializer(data=request.data)
        _ = serializer.is_valid(raise_exception=True)

        destination_test = get_destination_test(
            destination=serializer.validated_data["destination"]["type"],
        )
        test_configuration = serializer.validated_data["destination"]["config"]
        destination_test.configure(**test_configuration)

        result = destination_test.run_step(test_step)
        return response.Response(result.as_dict())

    @action(methods=["POST"], detail=True, required_scopes=["INTERNAL"])
    def run_test_step(self, request: request.Request, *args, **kwargs) -> response.Response:
        test_step = request.data.pop("step", 0)

        serializer = self.get_serializer(data=request.data)
        _ = serializer.is_valid(raise_exception=True)

        destination_test = get_destination_test(
            destination=serializer.validated_data["destination"]["type"],
        )
        batch_export = self.get_object()
        test_configuration = {**batch_export.destination.config, **serializer.validated_data["destination"]["config"]}
        destination_test.configure(**test_configuration)

        result = destination_test.run_step(test_step)
        return response.Response(result.as_dict())


class BatchExportOrganizationViewSet(BatchExportViewSet):
    filter_rewrite_rules = {"organization_id": "team__organization_id"}


@dataclass
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

        if obj.start_at is None:
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
        The backfill workflow ID
    """
    temporal = sync_connect()

    if start_at_input is not None:
        start_at = validate_date_input(start_at_input, team)
    else:
        start_at = None

    if end_at_input is not None:
        end_at = validate_date_input(end_at_input, team)
    else:
        end_at = None

    if (start_at is not None or end_at is not None) and batch_export.model is not None:
        try:
            earliest_backfill_start_at = fetch_earliest_backfill_start_at(
                team_id=team.pk,
                model=batch_export.model,
                interval_time_delta=batch_export.interval_time_delta,
                exclude_events=batch_export.destination.config.get("exclude_events", []),
                include_events=batch_export.destination.config.get("include_events", []),
            )
            if earliest_backfill_start_at is None:
                raise ValidationError("There is no data to backfill for this model.")

            earliest_backfill_start_at = earliest_backfill_start_at.astimezone(team.timezone_info)

            if end_at is not None and end_at < earliest_backfill_start_at:
                raise ValidationError(
                    "The provided backfill date range contains no data. The earliest possible backfill start date is "
                    f"{earliest_backfill_start_at.strftime('%Y-%m-%d %H:%M:%S')}",
                )

            if start_at is not None and start_at < earliest_backfill_start_at:
                logger.info(
                    "Backfill start_at '%s' is before the earliest possible backfill start_at '%s', setting start_at "
                    "to earliest_backfill_start_at",
                    start_at,
                    earliest_backfill_start_at,
                )
                start_at = earliest_backfill_start_at
        except NotImplementedError:
            logger.warning("No backfill check implemented for model: '%s'; skipping", batch_export.model)

    if start_at is None or end_at is None:
        return backfill_export(temporal, str(batch_export.pk), team.pk, start_at, end_at)

    if start_at >= end_at:
        raise ValidationError("The initial backfill datetime 'start_at' happens after 'end_at'")

    if end_at > dt.datetime.now(dt.UTC) + batch_export.interval_time_delta:
        raise ValidationError(
            f"The provided 'end_at' ({end_at.isoformat()}) is too far into the future. Cannot backfill beyond 1 batch period into the future."
        )

    try:
        return backfill_export(temporal, str(batch_export.pk), team.pk, start_at, end_at)
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
            batch_export = BatchExport.objects.get(
                id=self.kwargs["parent_lookup_batch_export_id"], team_id=self.team_id
            )
        except BatchExport.DoesNotExist:
            raise NotFound("BatchExport not found.")

        backfill_workflow_id = create_backfill(
            self.team,
            batch_export,
            request.data.get("start_at"),
            request.data.get("end_at"),
        )
        return response.Response({"backfill_id": backfill_workflow_id})

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
