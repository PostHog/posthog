import datetime as dt
from typing import Any, TypedDict, cast

import posthoganalytics
import structlog
from django.db import transaction
from django.utils.timezone import now
from rest_framework import mixins, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.pagination import CursorPagination
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.batch_exports.models import (
    BATCH_EXPORT_INTERVALS,
    BatchExportLogEntry,
    BatchExportLogEntryLevel,
    fetch_batch_export_log_entries,
)
from posthog.batch_exports.service import (
    BatchExportIdError,
    BatchExportSchema,
    BatchExportServiceError,
    BatchExportServiceRPCError,
    BatchExportServiceScheduleNotFound,
    BatchExportWithNoEndNotAllowedError,
    backfill_export,
    batch_export_delete_schedule,
    cancel_running_batch_export_backfill,
    pause_batch_export,
    sync_batch_export,
    unpause_batch_export,
)
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
from posthog.temporal.common.client import sync_connect
from posthog.utils import relative_date_parse

logger = structlog.get_logger(__name__)


def validate_date_input(date_input: Any) -> dt.datetime:
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
        parsed = dt.datetime.fromisoformat(date_input.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValidationError(f"Input {date_input} is not a valid ISO formatted datetime.")
    return parsed


class BatchExportRunSerializer(serializers.ModelSerializer):
    """Serializer for a BatchExportRun model."""

    class Meta:
        model = BatchExportRun
        fields = "__all__"
        # TODO: Why aren't all these read only?
        read_only_fields = ["batch_export"]


class RunsCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 100


class BatchExportRunViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "batch_export"
    queryset = BatchExportRun.objects.all()
    serializer_class = BatchExportRunSerializer
    pagination_class = RunsCursorPagination

    def get_queryset(self, date_range: tuple[dt.datetime, dt.datetime] | None = None):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        if date_range:
            return self.queryset.filter(
                batch_export_id=self.kwargs["parent_lookup_batch_export_id"],
                created_at__range=date_range,
            ).order_by("-created_at")
        else:
            return self.queryset.filter(batch_export_id=self.kwargs["parent_lookup_batch_export_id"]).order_by(
                "-created_at"
            )

    def list(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Get all BatchExportRuns for a BatchExport."""
        if not isinstance(request.user, User) or request.user.team is None:
            raise NotAuthenticated()

        after = self.request.query_params.get("after", "-7d")
        before = self.request.query_params.get("before", None)
        after_datetime = relative_date_parse(after, request.user.team.timezone_info)
        before_datetime = relative_date_parse(before, request.user.team.timezone_info) if before else now()
        date_range = (after_datetime, before_datetime)

        page = self.paginate_queryset(self.get_queryset(date_range=date_range))
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)


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
    def to_internal_value(self, data: str) -> ast.SelectQuery | ast.SelectUnionQuery:
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
        except errors.ResolverException:
            raise serializers.ValidationError("Invalid HogQL query")

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
        context = HogQLContext(
            team_id=self.context["team_id"],
            enable_select_queries=True,
            limit_top_select=False,
        )

        try:
            batch_export_schema: BatchExportsSchema = {
                "fields": [],
                "values": {},
                "hogql_query": print_prepared_ast(hogql_query, context=context, dialect="hogql"),
            }
        except errors.HogQLException:
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

    def validate_hogql_query(self, hogql_query: ast.SelectQuery | ast.SelectUnionQuery) -> ast.SelectQuery:
        """Validate a HogQLQuery being used for batch exports.

        This method essentially checks that a query is supported by batch exports:
        1. UNION ALL is not supported.
        2. Any JOINs are not supported.
        3. Query must SELECT FROM events, and only from events.
        """

        if isinstance(hogql_query, ast.SelectUnionQuery):
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


class BatchExportViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "batch_export"
    queryset = BatchExport.objects.all()
    serializer_class = BatchExportSerializer

    def get_queryset(self):
        if not isinstance(self.request.user, User):
            raise NotAuthenticated()

        return super().get_queryset().exclude(deleted=True).order_by("-created_at").prefetch_related("destination")

    @action(methods=["POST"], detail=True)
    def backfill(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Trigger a backfill for a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        start_at_input = request.data.get("start_at", None)
        end_at_input = request.data.get("end_at", None)

        if start_at_input is None or end_at_input is None:
            raise ValidationError("Both 'start_at' and 'end_at' must be specified")

        start_at = validate_date_input(start_at_input)
        end_at = validate_date_input(end_at_input)

        if start_at >= end_at:
            raise ValidationError("The initial backfill datetime 'start_at' happens after 'end_at'")

        team_id = request.user.current_team.id

        batch_export = self.get_object()
        temporal = sync_connect()
        try:
            backfill_id = backfill_export(temporal, str(batch_export.pk), team_id, start_at, end_at)
        except BatchExportWithNoEndNotAllowedError:
            raise ValidationError("Backfilling a BatchExport with no end date is not allowed")

        return response.Response({"backfill_id": backfill_id})

    @action(methods=["POST"], detail=True)
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

    @action(methods=["POST"], detail=True)
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
        temporal = sync_connect()

        instance.deleted = True

        try:
            batch_export_delete_schedule(temporal, str(instance.pk))
        except BatchExportServiceScheduleNotFound as e:
            logger.warning(
                "The Schedule %s could not be deleted as it was not found",
                e.schedule_id,
            )

        instance.save()

        for backfill in BatchExportBackfill.objects.filter(batch_export=instance):
            if backfill.status == BatchExportBackfill.Status.RUNNING:
                cancel_running_batch_export_backfill(temporal, backfill.workflow_id)


class BatchExportOrganizationViewSet(BatchExportViewSet):
    filter_rewrite_rules = {"organization_id": "team__organization_id"}


class BatchExportLogEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = BatchExportLogEntry


class BatchExportLogViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    scope_object = "batch_export"
    serializer_class = BatchExportLogEntrySerializer

    def get_queryset(self):
        limit_raw = self.request.GET.get("limit")
        limit: int | None
        if limit_raw:
            try:
                limit = int(limit_raw)
            except ValueError:
                raise ValidationError("Query param limit must be omitted or an integer!")
        else:
            limit = None

        after_raw: str | None = self.request.GET.get("after")
        after: dt.datetime | None = None
        if after_raw is not None:
            after = dt.datetime.fromisoformat(after_raw.replace("Z", "+00:00"))

        before_raw: str | None = self.request.GET.get("before")
        before: dt.datetime | None = None
        if before_raw is not None:
            before = dt.datetime.fromisoformat(before_raw.replace("Z", "+00:00"))

        level_filter = [BatchExportLogEntryLevel[t.upper()] for t in (self.request.GET.getlist("level_filter", []))]
        return fetch_batch_export_log_entries(
            team_id=self.parents_query_dict["team_id"],
            batch_export_id=self.parents_query_dict["batch_export_id"],
            run_id=self.parents_query_dict.get("run_id", None),
            after=after,
            before=before,
            search=self.request.GET.get("search"),
            limit=limit,
            level_filter=level_filter,
        )
