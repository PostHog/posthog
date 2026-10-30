"""Batch export endpoints: create, update, pause, unpause, delete and destination tests."""

import uuid
import typing
import dataclasses
from typing import cast

from django.db import transaction

import posthoganalytics
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import request, response, serializers, status, viewsets
from rest_framework.exceptions import NotAuthenticated, NotFound, PermissionDenied, ValidationError

from posthog.schema import HogQLQueryModifiers, MaterializationMode, PersonsOnEventsMode

from posthog.hogql import ast, errors
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.integrations import IntegrationRecord
from posthog.models import Team, User

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.batch_exports.backend.facade import api as batch_exports_api
from products.batch_exports.backend.facade.contracts import (
    BatchExportNotFoundError,
    BatchExportScheduleError,
    InvalidBatchExportDestinationError,
    InvalidBatchExportFilters,
    UnsupportedDestinationTestError,
)
from products.batch_exports.backend.facade.enums import (
    EXPORTABLE_EVENTS_MODEL_FIELDS,
    SUPPORTED_FILTER_TYPES_DISPLAY,
    TIMEZONES,
    BatchExportDestinationType,
    BatchExportInterval,
    BatchExportModel,
    IncrementalMode,
)
from products.batch_exports.backend.hogql_source import (
    UnsupportedHogQLQueryError,
    load_hogql_modifiers,
    serialize_batch_export_query,
    validate_hogql_query_for_batch_export,
)
from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination, BatchExportSource
from products.batch_exports.backend.presentation.views.utils import (
    HOGQL_MODIFIERS_HELP_TEXT,
    HogQLModifiersField,
    check_high_frequency_batch_exports_enabled,
    check_hogql_batch_exports_enabled,
)
from products.batch_exports.backend.service import BatchExportSchema, sync_batch_export

from . import (
    destinations as destination_views,
    runs as run_views,
)

HOGQL_QUERY_HELP_TEXT = (
    "HogQL SELECT query. With model 'hogql', its results are the data exported by every run. "
    "The query may reference the {data_interval_start} and {data_interval_end} placeholders, "
    "replaced with each run's data interval bounds, for example: "
    "WHERE timestamp >= {data_interval_start} AND timestamp < {data_interval_end}. "
    "Without them every run exports all rows the query returns. "
    "Required when model is 'hogql'."
)


class BatchExportUnpauseRequestSerializer(serializers.Serializer):
    backfill = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to backfill the runs that the batch export missed while it was paused.",
    )


class DestinationTestStepRequestSerializer(serializers.Serializer):
    step = serializers.IntegerField(
        default=0,
        help_text="Index of the connection test step to run. Steps start at 0.",
    )


class BatchExportRequestSerializer(serializers.Serializer):
    """Request body for create/partial_update on BatchExportViewSet.

    Mirrors the writeable fields of `BatchExportSerializer` but uses a polymorphic
    `destination` schema so integration_id is marked required on the types that need
    it. Responses continue to use `BatchExportSerializer`.
    """

    name = serializers.CharField(help_text="Human-readable name for the batch export.")
    model = serializers.ChoiceField(
        choices=BatchExportModel.choices,
        default=serializers.CreateOnlyDefault(BatchExportModel.EVENTS),  # type: ignore[arg-type]
        help_text=(
            "Which data model to export: events, persons, sessions, or hogql. "
            "The hogql model exports the results of hogql_query."
        ),
    )
    destination = destination_views.BatchExportDestinationRequestField(
        help_text="Destination configuration. Required integration_id is enforced per destination type.",
    )
    interval = serializers.ChoiceField(
        choices=BatchExportInterval.choices,
        help_text="How often the batch export should run.",
    )
    paused = serializers.BooleanField(required=False, help_text="Whether the batch export is paused.")
    hogql_query = serializers.CharField(
        required=False,
        allow_null=True,
        help_text=HOGQL_QUERY_HELP_TEXT,
    )
    hogql_modifiers = HogQLModifiersField(
        required=False,
        allow_null=True,
        help_text=HOGQL_MODIFIERS_HELP_TEXT,
    )
    primary_key = serializers.ListField(
        child=serializers.CharField(allow_null=False, allow_blank=False),
        required=False,
        allow_null=True,
        allow_empty=False,
        help_text="The column or columns in the provided HogQL query that make up the primary key for a HogQL-backed batch export. Required if incremental mode is 'MERGE'",
    )
    version_key = serializers.ListField(
        child=serializers.CharField(allow_null=False, allow_blank=False),
        required=False,
        allow_null=True,
        allow_empty=False,
        help_text="The column or columns in the provided HogQL query that make up the version key for a HogQL-backed batch export.",
    )
    incremental_mode = serializers.ChoiceField(
        choices=IncrementalMode.choices,
        default=serializers.CreateOnlyDefault(IncrementalMode.APPEND),  # type: ignore[arg-type]
        help_text="How this batch export handles incremental updates.",
    )
    filters = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text=(
            "Optional list of property filters to restrict which events are exported. Each filter is a "
            f"serialized HogQL property filter object with a 'type' of one of: {SUPPORTED_FILTER_TYPES_DISPLAY} "
            '(e.g. {"key": "$browser", "operator": "exact", "type": "event", "value": ["Firefox"]}).'
        ),
    )
    timezone = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="IANA timezone name (e.g. 'America/New_York', 'Europe/London', 'UTC') controlling daily and weekly interval boundaries.",
    )
    offset_day = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=6,
        help_text="Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday).",
    )
    offset_hour = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=23,
        help_text="Hour-of-day offset (0-23) for daily and weekly intervals.",
    )


def parse_events_hogql_query(hogql_query: str, team_id: int, user: User | None) -> ast.SelectQuery | ast.SelectSetQuery:
    """Parse a HogQL SelectQuery from a string query."""
    try:
        parsed_query = parse_select(hogql_query)
    except Exception:
        raise serializers.ValidationError("Failed to parse query")

    try:
        restricted_properties = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)
        context = HogQLContext(
            team_id=team_id,
            user=user,
            enable_select_queries=True,
            restricted_properties=restricted_properties,
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )
        if restricted_properties:
            # A restricted query is stored without its HogQL text, so no run can recompile it for
            # the native source, where a materialized column does not exist.
            context.modifiers.materializationMode = MaterializationMode.DISABLED
        use_native_schema = context.uses_new_events_schema()
        prepared_select_query = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(
                parsed_query, context=context, dialect="hogql" if use_native_schema else "clickhouse"
            ),
        )
        if use_native_schema:
            resolve_types(clone_expr(parsed_query, clear_types=True), context=context, dialect="clickhouse")
    except errors.ExposedHogQLError as e:
        raise serializers.ValidationError(f"Invalid HogQL query: {e}")

    return prepared_select_query


class _SubqueryFinder(TraversingVisitor):
    """Walk an AST subtree and flag if any SelectQuery or SelectSetQuery is found."""

    def __init__(self):
        super().__init__()
        self.found = False

    def visit_select_query(self, node: ast.SelectQuery):
        self.found = True

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        self.found = True


class _DatabaseFieldFinder(TraversingVisitor):
    """Walk an AST subtree and collect the names of the database fields it reads."""

    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context
        self.names: set[str] = set()

    def visit_field(self, node: ast.Field):
        resolve = getattr(node.type, "resolve_database_field", None)
        if resolve is not None:
            database_field = resolve(self.context)
            name = getattr(database_field, "name", None)
            if name is not None:
                self.names.add(name)
        super().visit_field(node)


class BatchExportSerializer(serializers.ModelSerializer):
    """Serializer for a BatchExport model."""

    model = serializers.ChoiceField(
        choices=BatchExportModel.choices,
        default=serializers.CreateOnlyDefault(BatchExportModel.EVENTS),  # type: ignore[arg-type]
        help_text=(
            "Which data model to export: events, persons, sessions, or hogql. "
            "The hogql model exports the results of hogql_query."
        ),
    )
    destination = destination_views.BatchExportDestinationSerializer(
        help_text="Destination configuration (type, config, and optional integration)."
    )
    latest_runs = run_views.BatchExportRunSerializer(
        many=True,
        read_only=True,
        help_text="The 10 most recent runs of this batch export, ordered newest first.",
    )
    interval = serializers.ChoiceField(
        choices=BatchExportInterval.choices,
        help_text="How often the batch export should run.",
    )
    hogql_query = serializers.CharField(
        required=False,
        allow_null=True,
        help_text=HOGQL_QUERY_HELP_TEXT,
    )
    hogql_modifiers = HogQLModifiersField(
        required=False,
        allow_null=True,
        help_text=HOGQL_MODIFIERS_HELP_TEXT,
    )
    primary_key = serializers.ListField(
        child=serializers.CharField(allow_null=False, allow_blank=False),
        required=False,
        allow_null=True,
        allow_empty=False,
        help_text="The column or columns in the provided HogQL query that make up the primary key for a HogQL-backed batch export. Required if incremental mode is 'MERGE'.",
    )
    version_key = serializers.ListField(
        child=serializers.CharField(allow_null=False, allow_blank=False),
        required=False,
        allow_null=True,
        allow_empty=False,
        help_text="The column or columns in the provided HogQL query that make up the version key for a HogQL-backed batch export.",
    )
    incremental_mode = serializers.ChoiceField(
        choices=IncrementalMode.choices,
        default=serializers.CreateOnlyDefault(IncrementalMode.APPEND),  # type: ignore[arg-type]
        help_text="How this batch export handles incremental updates.",
    )
    timezone = serializers.ChoiceField(
        choices=TIMEZONES,
        required=False,
        allow_null=True,
        help_text="IANA timezone name controlling daily and weekly interval boundaries. Defaults to UTC.",
    )
    offset_day = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=6,
        help_text="Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday). Only valid when interval is 'week'.",
    )
    offset_hour = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=23,
        help_text="Hour-of-day offset (0-23) for daily and weekly intervals. Only valid when interval is 'day' or 'week'.",
    )

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
            "hogql_modifiers",
            "primary_key",
            "version_key",
            "incremental_mode",
            "schema",
            "filters",
            "timezone",
            "offset_day",
            "offset_hour",
        ]
        read_only_fields = ["id", "team_id", "created_at", "last_updated_at", "latest_runs", "schema"]

    def validate(self, attrs: dict) -> dict:
        """Validate this batch export.

        Delegates to validation functions that require the full attrs to complete
        validation.
        """
        attrs = self._validate_interval_offset(attrs)

        model = self._get_model(attrs)
        destination = attrs.get("destination")
        if destination and destination.get("type") == BatchExportDestinationType.HTTP:
            if model != BatchExportModel.EVENTS:
                raise serializers.ValidationError("HTTP batch exports only support the events model")

        self._validate_attribute_only_supported_for_model(attrs, name="filters", model=BatchExportModel.EVENTS)
        self._validate_attribute_only_supported_for_model(attrs, name="hogql_modifiers", model=BatchExportModel.HOGQL)

        # Pre-defined models have these values hard-coded, only HogQL allows user input
        self._validate_attribute_only_supported_for_model(attrs, name="primary_key", model=BatchExportModel.HOGQL)
        self._validate_attribute_only_supported_for_model(attrs, name="version_key", model=BatchExportModel.HOGQL)

        # TODO: Once these teams are migrated, remove this.
        if model == BatchExportModel.EVENTS and (hogql_query := attrs.get("hogql_query")) is not None:
            is_grandfathered_team_id = BatchExport.objects.filter(
                schema__isnull=False, team=self.context["get_team"]()
            ).exists()
            if is_grandfathered_team_id:
                attrs["hogql_query"] = self._validate_events_hogql_query(hogql_query)
            else:
                self._validate_attribute_only_supported_for_model(
                    attrs, name="hogql_query", model=BatchExportModel.HOGQL
                )
        else:
            self._validate_attribute_only_supported_for_model(attrs, name="hogql_query", model=BatchExportModel.HOGQL)

        if model == BatchExportModel.HOGQL:
            self._validate_hogql_query(attrs)

        return attrs

    def _validate_interval_offset(self, attrs: dict) -> dict:
        interval = attrs.get("interval")

        if interval is None:
            return attrs

        # Convert offset_day and offset_hour to interval_offset
        # Check if offset fields are in the request (for PATCH, distinguish between absent and None)
        offset_day_provided = "offset_day" in attrs
        offset_hour_provided = "offset_hour" in attrs
        offset_day = attrs.pop("offset_day", None)
        offset_hour = attrs.pop("offset_hour", None)

        if interval == "day":
            # For daily exports, only offset_hour is used
            if offset_day_provided and offset_day is not None:
                raise serializers.ValidationError(
                    {"offset_day": "offset_day should not be specified for daily intervals"}
                )

            if offset_hour_provided:
                # User explicitly provided offset_hour (even if None)
                attrs["interval_offset"] = offset_hour * 3600 if offset_hour is not None else None
            elif not self.partial:
                # PUT or new instance: default to None if not provided
                attrs["interval_offset"] = None
            # otherwise if a PATCH and offset_hour is not provided, don't set interval_offset in attrs
            # to preserve existing value
        elif interval == "week":
            # For weekly exports, both offset_day and offset_hour are used
            if offset_day_provided or offset_hour_provided:
                day = offset_day or 0
                hour = offset_hour or 0
                attrs["interval_offset"] = day * 86400 + hour * 3600
            elif not self.partial:
                # PUT or new instance: default to None if not provided
                attrs["interval_offset"] = None
            # otherwise if a PATCH and offset fields not provided, don't set interval_offset in attrs
            # to preserve existing value
        else:
            # For other intervals, reset interval_offset to None
            # Also validate that offset fields are not provided
            if offset_day_provided and offset_day is not None:
                raise serializers.ValidationError(
                    {"offset_day": "offset_day is not applicable for non-daily/weekly intervals"}
                )
            if offset_hour_provided and offset_hour is not None:
                raise serializers.ValidationError(
                    {"offset_hour": "offset_hour is not applicable for non-daily/weekly intervals"}
                )
            attrs["interval_offset"] = None

        return attrs

    def _get_model(self, attrs: dict[str, typing.Any]) -> str:
        """Return this batch export's model, from `attrs` or current instance."""
        if self.instance is None:
            this_model: str = attrs["model"]  # Has a default, must be present
        else:
            # NOTE: We validate that model cannot change in validate_model, so
            # whether is present in attrs or not is irrelevant.
            this_model = self.instance.model
        return this_model

    def _validate_attribute_only_supported_for_model(
        self, attrs: dict[str, typing.Any], *, name: str, model: str
    ) -> None:
        """Validates attribute `name` is only provided for supported `model`.

        Raises:
            ValidationError: When this batch export's model is not `model` and
                a non-None `name` attribute value was included in the request.
        """
        if attrs.get(name) is None:
            return

        this_model = self._get_model(attrs)
        if this_model != model:
            raise serializers.ValidationError(
                {name: f"'{name}' is only supported for '{model}' not '{this_model}' model"}
            )

    def _validate_hogql_query(self, attrs: dict[str, typing.Any]) -> None:
        """Validate `hogql_query` for this batch export.

        Raises:
            ValidationError: When any of the following:
                1. No hogql_query was passed for a HogQL model.
                2. When a non-None hogql_query for a HogQL model is unsupported.
        """
        source = self.instance.source if self.instance is not None else None
        saved_query = source.hogql_query if source is not None else None

        hogql_query = attrs.get("hogql_query", saved_query)
        if hogql_query is None:
            raise serializers.ValidationError({"hogql_query": "'hogql_query' is required when 'model' is 'hogql'"})

        user = self.context["request"].user
        team = self.context["get_team"]()
        hogql_modifiers = self._get_hogql_modifiers(attrs)
        try:
            parsed = validate_hogql_query_for_batch_export(hogql_query, team, user=user, modifiers=hogql_modifiers)
        except UnsupportedHogQLQueryError as e:
            raise serializers.ValidationError({"hogql_query": str(e)}) from e

        # NOTE: Should be populated after a successful preparation
        assert isinstance(parsed.type, (ast.SelectQueryType, ast.SelectSetQueryType))
        output_columns = set(parsed.type.columns)

        saved_incremental_mode = self.instance.incremental_mode if self.instance is not None else None
        incremental_mode = attrs.get("incremental_mode", saved_incremental_mode)

        saved_primary_key = source.primary_key if source is not None else None
        primary_key = set(attrs.get("primary_key", saved_primary_key) or ())

        if not primary_key and incremental_mode == IncrementalMode.MERGE:
            raise serializers.ValidationError(
                {"primary_key": "'primary_key' is required when 'incremental_mode' is 'MERGE'"}
            )

        missing_primary_key = primary_key - output_columns

        if missing_primary_key:
            raise serializers.ValidationError(
                {
                    "primary_key": f"'primary_key' contains columns that are not present in the query: {', '.join(missing_primary_key)}"
                }
            )

        saved_version_key = source.version_key if source is not None else None
        version_key = set(attrs.get("version_key", saved_version_key) or ())
        missing_version_key = version_key - output_columns

        if missing_version_key:
            raise serializers.ValidationError(
                {
                    "version_key": f"'version_key' contains columns that are not present in the query: {','.join(missing_version_key)}"
                }
            )

    def _get_hogql_modifiers(self, attrs: dict[str, typing.Any]) -> HogQLQueryModifiers | None:
        if "hogql_modifiers" in attrs:
            if attrs["hogql_modifiers"] is None:
                modifiers: HogQLQueryModifiers | None = None
            else:
                # Modifiers were already validated and loaded by the field
                field = typing.cast(HogQLModifiersField, self.fields["hogql_modifiers"])
                modifiers = field.loaded
        else:
            source = self.instance.source if self.instance is not None else None
            # Modifiers are valid if present in the db, even if the function
            # re-validates them anyways.
            modifiers = load_hogql_modifiers(source.hogql_modifiers if source is not None else None)

        return modifiers

    def validate_model(self, model: str) -> str:
        """Validate the model is new or not changing when provided."""
        if model == BatchExportModel.HOGQL:
            team = self.context["get_team"]()
            check_hogql_batch_exports_enabled(team=team)

        if self.instance is None:
            return model

        current_model = self.instance.model
        if model != current_model:
            raise serializers.ValidationError("Changing models is not supported. Create a new batch export instead.")

        return model

    def validate_interval(self, interval: str) -> str:
        """Validate sub-hour frequency intervals are only available when feature flag is enabled."""
        if interval not in ("hour", "day", "week"):
            team = self.context["get_team"]()
            check_high_frequency_batch_exports_enabled(team=team)
        return interval

    def validate_timezone(self, timezone: str | None) -> str | None:
        """Validate timezone.

        We set the timezone to the default value of 'UTC' if it is None.

        NOTE: This only gets called if 'timezone' is provided in the request data.
        (i.e. if we're not patching the timezone this function is not called and the timezone remains unchanged)
        """

        if timezone is None:
            return "UTC"
        return timezone

    def validate_offset_day(self, offset_day: int | None) -> int | None:
        """Validate offset_day based on the interval.

        It should be between 0-6 (Sunday-Saturday) for weekly intervals (this is included in the IntegerField
        validation, so we don't need to validate it here).
        Sunday is 0 since this is what is used by Temporal and Sunday is also the default week start day in PostHog.

        It should be None for all other intervals.
        """
        interval = self.initial_data.get("interval")
        if interval is None and self.instance:
            interval = self.instance.interval

        if offset_day is None:
            return None

        if interval != "week":
            raise serializers.ValidationError("offset_day is not applicable for non-weekly intervals")

        return offset_day

    def validate_offset_hour(self, offset_hour: int | None) -> int | None:
        """Validate offset_hour based on the interval.

        Rules:
        1. offset_hour must be between 0-23 for daily and weekly intervals (this is included in the IntegerField
            validation, so we don't need to validate it here).
        2. offset_hour is not applicable for other intervals
        """
        interval = self.initial_data.get("interval")
        if interval is None and self.instance:
            interval = self.instance.interval

        if offset_hour is None:
            return None

        if interval not in ("day", "week"):
            raise serializers.ValidationError("offset_hour is not applicable for non-daily/weekly intervals")

        return offset_hour

    def validate_primary_key(self, primary_key: list[str] | None) -> list[str] | None:
        """Validate primary key contains no duplicates."""
        if not primary_key:
            return primary_key

        if not len(set(primary_key)) == len(primary_key):
            raise serializers.ValidationError("'primary_key' contains duplicate column names.")
        return primary_key

    def validate_version_key(self, version_key: list[str] | None) -> list[str] | None:
        """Validate version key contains no duplicates."""
        if not version_key:
            return version_key

        if not len(set(version_key)) == len(version_key):
            raise serializers.ValidationError("'version_key' contains duplicate column names.")
        return version_key

    def validate_filters(self, filters):
        try:
            batch_exports_api.validate_batch_export_filters(filters)
        except InvalidBatchExportFilters as e:
            raise serializers.ValidationError(str(e))
        return filters

    # TODO: could this be moved inside BatchExportDestinationSerializer::validate?
    def validate_destination(self, destination_attrs: dict):
        destination_type = destination_attrs["type"]
        view = self.context.get("view")

        export_id: uuid.UUID | None = None
        if self.instance is not None:
            export_id = self.instance.id
        elif view is not None and "pk" in view.kwargs:
            # Running validation for a `detail=True` action.
            export_id = uuid.UUID(str(view.kwargs["pk"]))

        integration: IntegrationRecord | None = destination_attrs.get("integration")
        try:
            batch_exports_api.validate_batch_export_destination(
                self.context["team_id"],
                export_id=export_id,
                destination_type=destination_type,
                config=destination_attrs["config"],
                integration_id=integration.id if integration is not None else None,
                integration_sent="integration" in destination_attrs,
            )
        except InvalidBatchExportDestinationError as e:
            raise serializers.ValidationError(str(e))
        except BatchExportNotFoundError:
            raise NotFound(f"BatchExport ID '{export_id}' not found.")

        if destination_type == BatchExportDestinationType.WORKFLOWS:
            team_id = self.context["team_id"]
            team = Team.objects.get(id=team_id)

            if not posthoganalytics.feature_enabled(
                "backfill-workflows-destination",
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
                raise PermissionDenied("Backfilling Workflows is not enabled for this team.")

        return destination_attrs

    def create(self, validated_data: dict) -> BatchExport:
        """Create a BatchExport."""
        destination_data = validated_data.pop("destination")
        team_id = self.context["team_id"]
        model = validated_data["model"]
        hogql_query = validated_data.pop("hogql_query", None)
        hogql_modifiers = validated_data.pop("hogql_modifiers", None)
        primary_key = validated_data.pop("primary_key", None)
        version_key = validated_data.pop("version_key", None)

        source = None
        if model == BatchExportModel.HOGQL:
            source = BatchExportSource(
                team_id=team_id,
                hogql_query=hogql_query,
                hogql_modifiers=hogql_modifiers,
                primary_key=primary_key,
                version_key=version_key,
            )
        elif hogql_query is not None:
            # TODO: Migrate batch exports using a HogQL query to HogQL model.
            validated_data["schema"] = self.serialize_hogql_query_to_batch_export_schema(hogql_query)

        destination_data["config"] = batch_exports_api.prepare_new_destination_config(
            destination_data["type"], destination_data["config"]
        )

        destination = BatchExportDestination(**destination_data)
        user = self.context["request"].user
        if not isinstance(user, User):
            raise NotAuthenticated()

        batch_export = BatchExport(
            team_id=team_id,
            destination=destination,
            source=source,
            last_modified_by=user,
            **validated_data,
        )

        sync_batch_export(batch_export, created=True)

        with transaction.atomic():
            destination.save()

            if source is not None:
                source.save()

            batch_export.save()

        return batch_export

    def serialize_hogql_query_to_batch_export_schema(self, hogql_query: ast.SelectQuery) -> BatchExportSchema:
        """Return a batch export schema from a HogQL query ast."""
        request = self.context.get("request")
        user = request.user if request is not None else None
        restricted_properties = get_restricted_properties_with_group_type_index_for_team(
            user=user, team_id=self.context["team_id"]
        )
        context = HogQLContext(
            team_id=self.context["team_id"],
            user=user,
            enable_select_queries=True,
            limit_top_select=False,
            restricted_properties=restricted_properties,
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            ),
        )
        if context.uses_new_events_schema():
            context.modifiers.materializationMode = MaterializationMode.DISABLED
        try:
            schema = serialize_batch_export_query(hogql_query, context)
        except errors.ExposedHogQLError:
            raise serializers.ValidationError("Unsupported HogQL query")
        if context.restricted_properties:
            schema.pop("hogql_query", None)
        return schema

    def _validate_events_hogql_query(self, hogql_query: str) -> ast.SelectQuery:
        """Validate a HogQL query being used for events batch exports.

        This method essentially checks that a query is supported by batch exports:
        1. UNION ALL is not supported.
        2. Any JOINs are not supported.
        3. Query must SELECT FROM events, and only from events.
        4. Subqueries in SELECT expressions are not supported.
        5. Query must select only from those fields we expose from the events table.
        """
        parsed = parse_events_hogql_query(
            hogql_query, team_id=self.context["team_id"], user=self.context["request"].user
        )

        if isinstance(parsed, ast.SelectSetQuery):
            raise serializers.ValidationError("UNIONs are not supported")

        parsed = cast(ast.SelectQuery, parsed)

        if parsed.select_from is None:
            raise serializers.ValidationError("Query must SELECT FROM events")

        if parsed.ctes:
            raise serializers.ValidationError("CTEs are not supported")

        if isinstance(parsed.select_from.table, (ast.SelectQuery, ast.SelectSetQuery)):
            raise serializers.ValidationError("Subqueries are not supported")

        # Not sure how to make mypy understand this works, hence the ignore comment.
        # And if it doesn't, it's still okay as it could mean an unsupported query.
        # We would come back with the example to properly type this.
        if parsed.select_from.table.chain != ["events"]:  # type: ignore
            raise serializers.ValidationError("Query must only SELECT FROM events")

        if parsed.select_from.next_join is not None:
            raise serializers.ValidationError("JOINs are not supported")

        subquery_finder = _SubqueryFinder()
        for field in parsed.select:
            subquery_finder.visit(field)
            if subquery_finder.found:
                raise serializers.ValidationError("Subqueries in SELECT expressions are not supported")

        # Check that the query only selects from those fields we expose from the events table.
        field_finder = _DatabaseFieldFinder(HogQLContext(team_id=self.context["team_id"], enable_select_queries=True))
        for field in parsed.select:
            field_finder.visit(field)

        unsupported = sorted(field_finder.names - EXPORTABLE_EVENTS_MODEL_FIELDS)
        if unsupported:
            raise serializers.ValidationError(
                f"Batch exports cannot read these fields: {', '.join(unsupported)}. "
                f"Supported fields are: {', '.join(sorted(EXPORTABLE_EVENTS_MODEL_FIELDS))}."
            )

        return parsed

    def update(self, batch_export: BatchExport, validated_data: dict) -> BatchExport:
        """Update a BatchExport."""
        destination_data = validated_data.pop("destination", None)

        missing = object()
        hogql_query = validated_data.pop("hogql_query", missing)
        hogql_modifiers = validated_data.pop("hogql_modifiers", missing)
        primary_key = validated_data.pop("primary_key", missing)
        version_key = validated_data.pop("version_key", missing)

        user = self.context["request"].user
        if not isinstance(user, User):
            raise NotAuthenticated()

        validated_data["last_modified_by"] = user

        with transaction.atomic():
            if destination_data:
                # Type changes are rejected by `validate_destination` — the incoming `type`
                # (if any) always equals the existing type by the time we get here.
                batch_export.destination.config = batch_exports_api.merge_destination_config(
                    batch_export.destination.type,
                    batch_export.destination.config,
                    destination_data.get("config", {}),
                )
                integration = destination_data.get("integration", batch_export.destination.integration)
                batch_export.destination.integration = integration

            if batch_export.model == BatchExportModel.HOGQL:
                hogql_attributes = (hogql_query, hogql_modifiers, primary_key, version_key)
                if any(attr is not missing for attr in hogql_attributes):
                    source = batch_export.source or BatchExportSource(team_id=batch_export.team_id)

                    if hogql_query is not missing:
                        source.hogql_query = hogql_query
                    if hogql_modifiers is not missing:
                        source.hogql_modifiers = hogql_modifiers
                    if primary_key is not missing:
                        source.primary_key = primary_key
                    if version_key is not missing:
                        source.version_key = version_key

                    source.save()
                    batch_export.source = source

            elif hogql_query is not missing:
                validated_data["schema"] = (
                    self.serialize_hogql_query_to_batch_export_schema(hogql_query) if hogql_query is not None else None
                )

            batch_export.destination.save()
            batch_export = super().update(batch_export, validated_data)

            sync_batch_export(batch_export, created=False)

        return batch_export


@extend_schema(tags=["batch_exports"])
@extend_schema_view(
    # Request bodies use a polymorphic destination schema so that integration-backed types
    # (Databricks, AzureBlob, BigQuery, Postgres, AwsS3, S3Compatible, Snowflake, Redshift) advertise
    # integration_id up front. It is required for every one of them; Postgres and Redshift exports
    # created before integrations keep their inline credentials on update.
    # Responses continue to use BatchExportSerializer.
    create=extend_schema(request=BatchExportRequestSerializer),
    update=extend_schema(request=BatchExportRequestSerializer),
    partial_update=extend_schema(request=BatchExportRequestSerializer),
)
class BatchExportViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, viewsets.ModelViewSet):
    scope_object = "batch_export"
    queryset = (
        BatchExport.objects.exclude(deleted=True)
        .order_by("-created_at")
        .prefetch_related("destination", "source")
        .all()
    )
    serializer_class = BatchExportSerializer
    log_source = "batch_exports"

    def safely_get_queryset(self, queryset):
        """Filter out batch exports with Workflows destination type if action is list."""
        if self.action == "list":
            return queryset.exclude(destination__type="Workflows")
        return queryset

    @extend_schema(request=None)
    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def pause(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Pause a BatchExport."""
        if not isinstance(request.user, User):
            raise NotAuthenticated()

        batch_export = self.get_object()
        user_id = request.user.distinct_id
        team_id = batch_export.team_id
        note = f"Pause requested by user {user_id} from team {team_id}"

        try:
            batch_exports_api.pause_batch_export(team_id, batch_export.id, note=note)
        except BatchExportNotFoundError:
            raise NotFound(f"BatchExport ID '{batch_export.id}' not found.")
        except BatchExportScheduleError:
            raise ValidationError("Invalid request to pause a BatchExport could not be carried out")

        return response.Response({"paused": True})

    @extend_schema(request=BatchExportUnpauseRequestSerializer)
    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def unpause(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Unpause a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        serializer = BatchExportUnpauseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        backfill = serializer.validated_data["backfill"]

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id
        note = f"Unpause requested by user {user_id} from team {team_id}"

        batch_export = self.get_object()

        try:
            batch_exports_api.unpause_batch_export(batch_export.team_id, batch_export.id, note=note, backfill=backfill)
        except BatchExportNotFoundError:
            raise NotFound(f"BatchExport ID '{batch_export.id}' not found.")
        except BatchExportScheduleError:
            raise ValidationError("Invalid request to unpause a BatchExport could not be carried out")

        return response.Response({"paused": False})

    def perform_destroy(self, instance: BatchExport):
        """Perform a BatchExport destroy by clearing Temporal and Django state.

        If the underlying Temporal Schedule doesn't exist, we ignore the error and proceed with the delete anyways.
        The Schedule could have been manually deleted causing Django and Temporal to go out of sync. For whatever reason,
        since we are deleting, we assume that we can recover from this state by finishing the delete operation by calling
        instance.save().
        """
        try:
            batch_exports_api.delete_batch_export(instance.id, instance.team_id)
        except BatchExportNotFoundError:
            raise NotFound(f"BatchExport ID '{instance.id}' not found.")

    def _parse_destination_test_step(self, request: request.Request) -> int:
        step_serializer = DestinationTestStepRequestSerializer(data=request.data)
        step_serializer.is_valid(raise_exception=True)
        request.data.pop("step", None)
        return step_serializer.validated_data["step"]

    def _run_destination_test_step(self, serializer: serializers.BaseSerializer, step: int) -> response.Response:
        destination = serializer.validated_data["destination"]
        integration: IntegrationRecord | None = destination.get("integration")
        try:
            result = batch_exports_api.run_destination_test_step(
                self.team_id,
                destination_type=destination["type"],
                config=destination["config"],
                integration_id=integration.id if integration else None,
                step=step,
            )
        except UnsupportedDestinationTestError:
            raise ValidationError(f"Connection tests aren't available for {destination['type']} destinations.")
        return response.Response(dataclasses.asdict(result))

    @action(methods=["GET"], detail=False, required_scopes=["batch_export:read"])
    def test(self, request: request.Request, *args, **kwargs) -> response.Response:
        destination = request.query_params.get("destination", None)
        if not destination:
            return response.Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            destination_test = batch_exports_api.describe_destination_test(destination)
        except UnsupportedDestinationTestError:
            return response.Response(status=status.HTTP_404_NOT_FOUND)

        return response.Response(dataclasses.asdict(destination_test))

    @action(methods=["POST"], detail=False, required_scopes=["batch_export:write"])
    def run_test_step_new(self, request: request.Request, *args, **kwargs) -> response.Response:
        test_step = self._parse_destination_test_step(request)

        serializer = self.get_serializer(data=request.data)
        _ = serializer.is_valid(raise_exception=True)

        return self._run_destination_test_step(serializer, test_step)

    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def run_test_step(self, request: request.Request, *args, **kwargs) -> response.Response:
        test_step = self._parse_destination_test_step(request)

        batch_export = self.get_object()
        try:
            stored_config = batch_exports_api.get_destination_test_config(batch_export.team_id, batch_export.id)
        except BatchExportNotFoundError:
            raise NotFound(f"BatchExport ID '{batch_export.id}' not found.")

        data = request.data
        data["destination"]["config"] = {**stored_config, **data["destination"]["config"]}

        serializer = self.get_serializer(data=data)
        _ = serializer.is_valid(raise_exception=True)

        return self._run_destination_test_step(serializer, test_step)
