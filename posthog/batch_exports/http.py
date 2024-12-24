import dataclasses
import datetime as dt
import types
import typing
from typing import Any, TypedDict, cast

import posthoganalytics
import structlog
from django.db import transaction
from django.utils.timezone import now
from rest_framework import filters, request, response, serializers, viewsets
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
    DESTINATION_WORKFLOWS,
    BatchExportIdError,
    BatchExportSchema,
    BatchExportServiceError,
    BatchExportServiceRPCError,
    BatchExportWithNoEndNotAllowedError,
    backfill_export,
    cancel_running_batch_export_run,
    disable_and_delete_export,
    pause_batch_export,
    sync_batch_export,
    unpause_batch_export,
)
from posthog.hogql import ast, errors
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.visitor import clone_expr
from posthog.models import (
    BatchExport,
    BatchExportDestination,
    BatchExportRun,
    Team,
    User,
)
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
        backfill_id = backfill_export(
            temporal,
            str(batch_export_run.batch_export.id),
            self.team_id,
            batch_export_run.data_interval_start,
            batch_export_run.data_interval_end,
        )

        return response.Response({"backfill_id": backfill_id})

    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def cancel(self, *args, **kwargs) -> response.Response:
        """Cancel a batch export run."""

        batch_export_run: BatchExportRun = self.get_object()

        temporal = sync_connect()
        # TODO: check status of run beforehand
        cancel_running_batch_export_run(temporal, batch_export_run)

        return response.Response({"cancelled": True})


class BatchExportDestinationConfigurationValidator:
    """Validator for a batch export destination configuration."""

    def __init__(self, type: str = "type", config: str = "config"):
        self.type_field = type
        self.config_field = config

    def __call__(self, attrs: dict):
        """Validate configuration values are compatible with destination inputs."""
        type = attrs[self.type_field]

        try:
            destination_inputs = DESTINATION_WORKFLOWS[type]
        except KeyError:
            raise serializers.ValidationError(
                f"Unsupported batch export destination: '{type}'", code="unsupported_destination"
            )

        config = attrs[self.config_field]

        for field in dataclasses.fields(destination_inputs):
            is_required = (
                field.default == dataclasses.MISSING
                and field.default_factory == dataclasses.MISSING
                # These two are required metadata fields but they are added by us.
                and field.name not in {"batch_export_id", "team_id"}
            )

            if is_required and field.name not in config:
                raise serializers.ValidationError(
                    f"The required configuration field '{field.name}' was not found", code="required_field"
                )

            provided_value = config.get(field.name, None)
            is_compatible = is_compatible_with_field(provided_value, field)

            if not is_compatible:
                raise serializers.ValidationError(
                    f"An unsupported value ('{provided_value}') was provided for the configuration field '{field.name}' of type '{field.type}'",
                    code="unsupported_value",
                )


def is_compatible_with_field(value: typing.Any, field: dataclasses.Field) -> bool:
    """Check if a value is compatible with a given dataclass field.

    Compatibility is defined as the value being of the expected type by the
    dataclass field.

    Arguments:
        value: The value to check
        field: The dataclass field we are checking for compatibility

    Returns:
        True if compatible, False otherwise.
    """
    origin = typing.get_origin(field.type)
    args = typing.get_args(field.type)

    # Unpack a Optional[X] union field to check its underlying type.
    if (origin is typing.Union or origin is types.UnionType) and len(args) == 2 and type(None) in args:
        if value is None:
            # Value not provided for an optional field is compatible
            return True

        non_none_type = next(t for t in args if t is not type(None))
        new_field = dataclasses.field()
        new_field.name = field.name
        new_field.type = non_none_type
        return is_compatible_with_field(value, new_field)

    # Unpack collection types to check underlying type of each element.
    if origin in {list, dict, set, tuple}:
        if not isinstance(value, origin):  # type: ignore
            return False

        if args:
            if origin is list or origin is set:
                new_field = dataclasses.field()
                new_field.name = field.name
                new_field.type = args[0]

                return all(is_compatible_with_field(v, new_field) for v in value)

            elif origin is dict:
                new_key_field = dataclasses.field()
                new_key_field.name = field.name
                new_key_field.type = args[0]

                new_value_field = dataclasses.field()
                new_value_field.name = field.name
                new_value_field.type = args[1]

                return all(
                    is_compatible_with_field(k, new_key_field) and is_compatible_with_field(v, new_value_field)
                    for k, v in value.items()
                )

            elif origin is tuple:
                if not len(value) == len(args):
                    return False

                for t, v in zip(args, value):
                    new_field = dataclasses.field()
                    new_field.name = field.name
                    new_field.type = t
                    is_compatible = is_compatible_with_field(v, new_field)

                    if not is_compatible:
                        return False

                return True

    # Check primitive types.
    return isinstance(value, field.type)  # type: ignore


class BatchExportDestinationSerializer(serializers.ModelSerializer):
    """Serializer for an BatchExportDestination model."""

    class Meta:
        model = BatchExportDestination
        fields = ["type", "config"]
        validators = [BatchExportDestinationConfigurationValidator()]

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
                    context=HogQLContext(team_id=self.context["team_id"], enable_select_queries=True),
                    dialect="hogql",
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
        ]
        read_only_fields = ["id", "team_id", "created_at", "last_updated_at", "latest_runs", "schema"]

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
                raise PermissionDenied("Higher frequency exports are not enabled for this team.")

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
            )
            print_prepared_ast(clone_expr(hogql_query), context=context, dialect="clickhouse")

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
    def backfill(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Trigger a backfill for a BatchExport."""
        start_at_input = request.data.get("start_at", None)
        end_at_input = request.data.get("end_at", None)

        temporal = sync_connect()
        batch_export = self.get_object()

        if start_at_input is not None:
            start_at = validate_date_input(start_at_input, self.team)
        else:
            start_at = None

        if end_at_input is not None:
            end_at = validate_date_input(end_at_input, self.team)
        else:
            end_at = None

        if start_at is None or end_at is None:
            backfill_id = backfill_export(temporal, str(batch_export.pk), self.team_id, start_at, end_at)
            return response.Response({"backfill_id": backfill_id})

        if start_at >= end_at:
            raise ValidationError("The initial backfill datetime 'start_at' happens after 'end_at'")

        if end_at > dt.datetime.now(dt.UTC) + batch_export.interval_time_delta:
            raise ValidationError(
                f"The provided 'end_at' ({end_at.isoformat()}) is too far into the future. Cannot backfill beyond 1 batch period into the future."
            )

        try:
            backfill_id = backfill_export(temporal, str(batch_export.pk), self.team_id, start_at, end_at)
        except BatchExportWithNoEndNotAllowedError:
            raise ValidationError("Backfilling a BatchExport with no end date is not allowed")

        return response.Response({"backfill_id": backfill_id})

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

    def perform_destroy(self, instance: BatchExport):
        """Perform a BatchExport destroy by clearing Temporal and Django state.

        If the underlying Temporal Schedule doesn't exist, we ignore the error and proceed with the delete anyways.
        The Schedule could have been manually deleted causing Django and Temporal to go out of sync. For whatever reason,
        since we are deleting, we assume that we can recover from this state by finishing the delete operation by calling
        instance.save().
        """
        disable_and_delete_export(instance)


class BatchExportOrganizationViewSet(BatchExportViewSet):
    filter_rewrite_rules = {"organization_id": "team__organization_id"}
