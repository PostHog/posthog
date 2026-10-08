"""Batch export endpoints: create, update, pause, unpause, delete and destination tests."""

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
from posthog.models import Team, User
from posthog.models.integration import (
    AzureBlobIntegration,
    AzureBlobIntegrationError,
    DatabricksIntegration,
    DatabricksIntegrationError,
    Integration,
    SnowflakeIntegration,
    SnowflakeIntegrationError,
)
from posthog.security.url_validation import (
    INVALID_HOST_MESSAGE,
    UNREACHABLE_HOST_MESSAGE,
    ShapeError,
    validate_external_host,
)
from posthog.temporal.common.client import sync_connect

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.batch_exports.backend.facade.contracts import InvalidBatchExportFilters
from products.batch_exports.backend.filters import SUPPORTED_FILTER_TYPES_DISPLAY, validate_batch_export_filters
from products.batch_exports.backend.hogql_source import (
    UnsupportedHogQLQueryError,
    load_hogql_modifiers,
    serialize_batch_export_query,
    validate_hogql_query_for_batch_export,
)
from products.batch_exports.backend.models.batch_export import (
    BATCH_EXPORT_INTERVALS,
    S3_FAMILY_TYPES,
    TIMEZONES,
    BatchExport,
    BatchExportDestination,
    BatchExportSource,
)
from products.batch_exports.backend.presentation.views.destination_tests import get_destination_test
from products.batch_exports.backend.presentation.views.utils import (
    HOGQL_MODIFIERS_HELP_TEXT,
    HogQLModifiersField,
    check_hogql_batch_exports_enabled,
)
from products.batch_exports.backend.service import (
    DESTINATION_WORKFLOWS,
    BaseBatchExportInputs,
    BatchExportIdError,
    BatchExportSchema,
    BatchExportServiceError,
    BatchExportServiceRPCError,
    delete_batch_export,
    pause_batch_export,
    sync_batch_export,
    unpause_batch_export,
)
from products.batch_exports.backend.temporal.destinations.constants import (
    AZURE_BLOB_SUPPORTED_COMPRESSIONS,
    S3_SUPPORTED_COMPRESSIONS,
)
from products.batch_exports.backend.temporal.sql.events import EXPORTABLE_EVENTS_MODEL_FIELDS

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
    "With model 'events', it defines a custom schema of columns to export instead. "
    "Required when model is 'hogql'."
)


class BatchExportUnpauseRequestSerializer(serializers.Serializer):
    backfill = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to backfill the runs that the batch export missed while it was paused.",
    )


class BatchExportRequestSerializer(serializers.Serializer):
    """Request body for create/partial_update on BatchExportViewSet.

    Mirrors the writeable fields of `BatchExportSerializer` but uses a polymorphic
    `destination` schema so integration_id is marked required on the types that need
    it. Responses continue to use `BatchExportSerializer`.
    """

    name = serializers.CharField(help_text="Human-readable name for the batch export.")
    model = serializers.ChoiceField(
        choices=BatchExport.Model.choices,
        default=serializers.CreateOnlyDefault(BatchExport.Model.EVENTS),  # type: ignore[arg-type]
        help_text=(
            "Which data model to export: events, persons, sessions, or hogql. "
            "The hogql model exports the results of hogql_query."
        ),
    )
    destination = destination_views.BatchExportDestinationRequestField(
        help_text="Destination configuration. Required integration_id is enforced per destination type.",
    )
    interval = serializers.ChoiceField(
        choices=BATCH_EXPORT_INTERVALS,
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
        choices=BatchExport.Model.choices,
        default=serializers.CreateOnlyDefault(BatchExport.Model.EVENTS),  # type: ignore[arg-type]
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
        choices=BATCH_EXPORT_INTERVALS,
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
            "schema",
            "filters",
            "timezone",
            "offset_day",
            "offset_hour",
        ]
        read_only_fields = ["id", "team_id", "created_at", "last_updated_at", "latest_runs", "schema"]

    def validate(self, attrs: dict) -> dict:
        """Validate the batch export configuration."""
        # HTTP batch exports only support the events model
        destination = attrs.get("destination")
        if destination and destination.get("type") == BatchExportDestination.Destination.HTTP:
            model = attrs.get("model")
            if model is not None and model != "events":
                raise serializers.ValidationError("HTTP batch exports only support the events model")

        # Convert offset_day and offset_hour to interval_offset
        interval = attrs.get("interval")
        if interval is not None:
            # Check if offset fields are in the request (for PATCH, distinguish between absent and None)
            offset_day_provided = "offset_day" in attrs
            offset_hour_provided = "offset_hour" in attrs
            offset_day = attrs.pop("offset_day", None)
            offset_hour = attrs.pop("offset_hour", None)

            if interval == "day":
                # For daily exports, only offset_hour is used
                if offset_day_provided and offset_day is not None:
                    raise serializers.ValidationError("offset_day should not be specified for daily intervals")

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
                    raise serializers.ValidationError("offset_day is not applicable for non-daily/weekly intervals")
                if offset_hour_provided and offset_hour is not None:
                    raise serializers.ValidationError("offset_hour is not applicable for non-daily/weekly intervals")
                attrs["interval_offset"] = None

        self._validate_model_query(attrs)

        return attrs

    def _validate_model_query(self, attrs: dict) -> None:
        """Validate `hogql_query` for the model the batch export ends up with."""
        current_model = self.instance.model if self.instance is not None else attrs["model"]
        model = attrs.get("model", current_model)

        if self.instance is not None and model != current_model and BatchExport.Model.HOGQL in (model, current_model):
            raise serializers.ValidationError(
                {"model": "Changing the model to or from 'hogql' is not supported. Create a new batch export instead."}
            )

        if model == BatchExport.Model.HOGQL:
            self._validate_hogql(attrs)
            return

        if attrs.get("hogql_modifiers") is not None:
            raise serializers.ValidationError(
                {"hogql_modifiers": "'hogql_modifiers' are only supported when 'model' is 'hogql'"}
            )

        if (hogql_query := attrs.get("hogql_query")) is not None:
            # For events model, we need the resolved AST.
            attrs["hogql_query"] = self._validate_events_hogql_query(hogql_query)

    def validate_interval(self, interval: str) -> str:
        """Validate sub-hour frequency intervals are only available when feature flag is enabled."""
        team_id = self.context["team_id"]

        if interval not in ("hour", "day", "week"):
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

    def validate_filters(self, filters):
        try:
            validate_batch_export_filters(filters)
        except InvalidBatchExportFilters as e:
            raise serializers.ValidationError(str(e))
        return filters

    # TODO: could this be moved inside BatchExportDestinationSerializer::validate?
    def validate_destination(self, destination_attrs: dict):
        destination_type = destination_attrs["type"]
        config = destination_attrs["config"]
        view = self.context.get("view")

        instance = None
        if self.instance is not None:
            instance = self.instance
            existing_config = instance.destination.config
        elif view is not None and "pk" in view.kwargs:
            # Running validation for a `detail=True` action.
            instance = view.get_object()
            existing_config = instance.destination.config
        else:
            existing_config = {}

        if instance is not None and destination_type != instance.destination.type:
            raise serializers.ValidationError(
                f"Cannot change destination type from '{instance.destination.type}' to '{destination_type}'. "
                "Delete this batch export and create a new one with the new destination type."
            )

        # This setting is used for grandfathered exports that used the legacy Parquet file extension,
        # and is a one-way migration; once exports use the new `.parquet` extension it is not
        # possible to go back to using the legacy extension.
        if config.get("legacy_parquet_extension") is True and not destination_views._uses_legacy_parquet_extension(
            destination_type, existing_config
        ):
            raise serializers.ValidationError(
                "'legacy_parquet_extension' can only stay on for an export that already writes the "
                "compression codec into its Parquet file names. It cannot be turned on for a new "
                "export, or turned back on once an export moved to the standard '.parquet' extension."
            )

        merged_config = recursive_dict_merge(existing_config, config)

        # SSRF protection for HTTP batch exports
        if destination_type == BatchExportDestination.Destination.HTTP:
            url = merged_config.get("url")
            if url and url not in ("https://us.i.posthog.com/batch/", "https://eu.i.posthog.com/batch/"):
                raise serializers.ValidationError(f"Invalid destination URL: {url}")

        if destination_type == BatchExportDestination.Destination.SNOWFLAKE:
            integration: Integration | None = destination_attrs.get("integration")
            if integration is None and "integration" not in destination_attrs and instance is not None:
                # A PATCH may send config alone, which keeps the export's existing integration.
                # An explicit `integration: null` is a removal, and is rejected below.
                integration = instance.destination.integration

            if integration is None:
                raise serializers.ValidationError("Integration is required for Snowflake batch exports")

            # Also rejects an integration missing its account, user or authentication type, so a
            # half-built one fails here rather than on the export's first run.
            try:
                SnowflakeIntegration(integration)
            except SnowflakeIntegrationError as e:
                raise serializers.ValidationError(str(e))

        if destination_type in S3_FAMILY_TYPES:
            integration = destination_attrs.get("integration")
            if integration is None and "integration" not in destination_attrs and instance is not None:
                # A PATCH may send config alone, which keeps the export's existing integration.
                # An explicit `integration: null` is a removal, and is rejected below.
                integration = instance.destination.integration

            if integration is None:
                raise serializers.ValidationError(f"Integration is required for {destination_type} batch exports")

            # Credentials and the provider endpoint are not declared on the input dataclasses, so
            # `BatchExportDestinationSerializer.validate` already rejects them as unknown fields.

            # we already validate the required inputs in BatchExportDestinationSerializer::validate
            # so here we just ensure that the inputs are not empty
            required_non_empty_inputs = ["bucket_name", "region", "prefix"]

            empty_inputs = []

            for required_input in required_non_empty_inputs:
                value = config.get(required_input)
                if value is not None and isinstance(value, str) and value.strip() == "":
                    empty_inputs.append(required_input)

            if empty_inputs:
                raise serializers.ValidationError(f"The following inputs are empty: {empty_inputs}")

            # The integration must match the destination kind. (Team ownership is already enforced
            # by the team-scoped `integration` field, which can only resolve integrations belonging
            # to the request's team.)
            if integration.kind != destination_views.S3_DESTINATION_TO_INTEGRATION_KIND[destination_type]:
                raise serializers.ValidationError(
                    f"Integration provided is not an AWS S3 integration (got kind='{integration.kind}')"
                )

            # JSONLines is the default file format for S3 exports for legacy reasons
            file_format = merged_config.get("file_format", "JSONLines")
            supported_file_formats = S3_SUPPORTED_COMPRESSIONS.keys()
            if file_format not in supported_file_formats:
                raise serializers.ValidationError(
                    f"File format {file_format} is not supported. Supported file formats are {list(supported_file_formats)}"
                )
            compression = merged_config.get("compression", None)
            if compression and compression not in S3_SUPPORTED_COMPRESSIONS[file_format]:
                raise serializers.ValidationError(
                    f"Compression {compression} is not supported for file format {file_format}. Supported compressions are {S3_SUPPORTED_COMPRESSIONS[file_format]}"
                )

        if destination_type == BatchExportDestination.Destination.DATABRICKS:
            # validate the Integration is valid (this is mandatory for Databricks batch exports)
            integration = destination_attrs.get("integration")
            if integration is None:
                raise serializers.ValidationError("Integration is required for Databricks batch exports")
            if integration.kind != Integration.IntegrationKind.DATABRICKS:
                raise serializers.ValidationError("Integration is not a Databricks integration.")
            # try instantiate the integration to check if it's valid
            try:
                DatabricksIntegration(integration)
            except DatabricksIntegrationError as e:
                raise serializers.ValidationError(str(e))

        if destination_type == BatchExportDestination.Destination.POSTGRES:
            integration = destination_attrs.get("integration")
            # New Postgres exports must use an Integration for credentials. Exports created before
            # integrations existed keep their inline credentials, so only require it on create
            # (`instance is None`); existing inline-credential exports stay valid when edited.
            if integration is None and instance is None:
                raise serializers.ValidationError("Integration is required for Postgres batch exports")
            if integration is not None and integration.kind != Integration.IntegrationKind.POSTGRESQL:
                raise serializers.ValidationError("Integration is not a PostgreSQL integration.")

        if destination_type == BatchExportDestination.Destination.BIGQUERY:
            integration = destination_attrs.get("integration")
            if integration is None:
                raise serializers.ValidationError("Integration is required for BigQuery batch exports")
            if integration.kind != Integration.IntegrationKind.GOOGLE_CLOUD_SERVICE_ACCOUNT:
                raise serializers.ValidationError("Integration is not a Google Cloud service account integration.")

        if destination_type == BatchExportDestination.Destination.AZURE_BLOB:
            # validate the Integration is valid (this is mandatory for Azure Blob batch exports)
            integration = destination_attrs.get("integration")
            if integration is None:
                raise serializers.ValidationError("Integration is required for Azure Blob batch exports")
            if integration.kind != Integration.IntegrationKind.AZURE_BLOB:
                raise serializers.ValidationError("Integration is not an Azure Blob integration.")
            # try instantiate the integration to check if it's valid
            try:
                AzureBlobIntegration(integration)
            except AzureBlobIntegrationError as e:
                raise serializers.ValidationError(str(e))

            file_format = merged_config.get("file_format", "JSONLines")
            supported_file_formats = AZURE_BLOB_SUPPORTED_COMPRESSIONS.keys()
            if file_format not in supported_file_formats:
                raise serializers.ValidationError(
                    f"File format {file_format} is not supported. Supported file formats are {list(supported_file_formats)}"
                )
            compression = merged_config.get("compression", None)
            if compression and compression not in AZURE_BLOB_SUPPORTED_COMPRESSIONS[file_format]:
                raise serializers.ValidationError(
                    f"Compression {compression} is not supported for file format {file_format}. Supported compressions are {AZURE_BLOB_SUPPORTED_COMPRESSIONS[file_format]}"
                )

        if destination_type == BatchExportDestination.Destination.REDSHIFT:
            integration = destination_attrs.get("integration")

            # Sticky integration: an export that uses one cannot drop back to inline credentials.
            # TODO: remove this guard once inline credentials are gone.
            if instance is not None and instance.destination.integration is not None and integration is None:
                raise serializers.ValidationError(
                    "Cannot remove the integration from a Redshift batch export that uses one. "
                    "Re-send its `integration` to keep it (or a different one to swap)."
                )

            # New Redshift exports must use an Integration for credentials. Exports created before
            # integrations existed keep their inline credentials, so only require it on create
            # (`instance is None`); existing inline-credential exports stay valid when edited.
            if integration is None and instance is None:
                raise serializers.ValidationError("Integration is required for Redshift batch exports")

            if integration is not None:
                # (Team ownership is already enforced by the team-scoped `integration` field.)
                if integration.kind != Integration.IntegrationKind.AWS_REDSHIFT:
                    raise serializers.ValidationError("Integration is not a Redshift integration.")

                # Only plain Redshift integrations store a host; AWS-flavor ones obtain
                # temporary credentials for a cluster endpoint that stays in the export config.
                if "host" not in integration.config and not merged_config.get("host"):
                    raise serializers.ValidationError(
                        "A 'host' is required when using an AWS Redshift integration: "
                        "set it to the cluster or workgroup endpoint."
                    )

            mode = merged_config.get("mode")

            if mode == "COPY":
                copy_inputs = merged_config.get("copy_inputs", {})
                if not copy_inputs:
                    raise serializers.ValidationError("Missing required inputs for 'COPY'")

                required_inputs = {"s3_bucket", "region_name", "authorization", "bucket_credentials"}
                if required_inputs - copy_inputs.keys():
                    raise serializers.ValidationError("Missing required input for 'COPY'")

                credential_keys = {"aws_access_key_id", "aws_secret_access_key"}

                bucket_credentials = copy_inputs["bucket_credentials"]
                bucket_integration_id = destination_views._coerce_integration_id(bucket_credentials)
                authorization = copy_inputs.get("authorization")
                authorization_integration_id = destination_views._coerce_integration_id(authorization)

                existing_copy_inputs = existing_config.get("copy_inputs") or {}

                for field_name, copy_integration_id in (
                    ("bucket_credentials", bucket_integration_id),
                    ("authorization", authorization_integration_id),
                ):
                    # Sticky like the top-level integration: COPY credentials that reference an
                    # integration cannot drop back to inline values.
                    # TODO: remove this guard once integrations are mandatory for Redshift and
                    # inline credentials are gone.
                    if (
                        instance is not None
                        and copy_integration_id is None
                        and destination_views._coerce_integration_id(existing_copy_inputs.get(field_name)) is not None
                    ):
                        raise serializers.ValidationError(
                            f"Cannot switch '{field_name}' from an integration to inline credentials. "
                            "Send a different integration ID to swap, or omit the field to keep the current one."
                        )
                    if copy_integration_id is None:
                        continue
                    # These ids live inside `config` rather than the team-scoped `integration`
                    # field, so team ownership must be checked here.
                    if not Integration.objects.filter(
                        id=copy_integration_id,
                        team_id=self.context["team_id"],
                        kind=Integration.IntegrationKind.AWS_S3,
                    ).exists():
                        raise serializers.ValidationError(
                            f"'{field_name}' does not reference an AWS S3 integration of this project."
                        )

                if bucket_integration_id is None and (
                    not isinstance(bucket_credentials, dict) or credential_keys - bucket_credentials.keys()
                ):
                    raise serializers.ValidationError("Missing required bucket credentials for 'COPY'")

                if authorization_integration_id is None:
                    if isinstance(authorization, dict):
                        if credential_keys - authorization.keys():
                            raise serializers.ValidationError("Missing required credentials for 'COPY'")
                    elif isinstance(authorization, str):
                        if not authorization.strip():
                            raise serializers.ValidationError("Missing required IAM role for 'COPY'")
                    else:
                        raise serializers.ValidationError(
                            "Authorization for 'COPY' must be an IAM role ARN, AWS credentials, or an integration ID."
                        )

        if destination_type == BatchExportDestination.Destination.WORKFLOWS:
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

        if destination_type in (
            BatchExportDestination.Destination.POSTGRES,
            BatchExportDestination.Destination.REDSHIFT,
        ):
            # PostgreSQL-server integrations (Postgres, plain Redshift) keep the host in the
            # linked Integration; AWS Redshift integrations and inline configs keep it in
            # `config`. Prefer the Integration's host when it has one so we don't skip
            # SSRF validation (and don't `KeyError` on a `config` that has no `host`).
            integration = destination_attrs.get("integration")
            host = integration.config.get("host") if integration is not None else None
            if host is None:
                host = merged_config.get("host")

            if host is not None:
                try:
                    validate_external_host(host)
                except ShapeError:
                    raise serializers.ValidationError(INVALID_HOST_MESSAGE)
                except ValueError:
                    raise serializers.ValidationError(UNREACHABLE_HOST_MESSAGE)

        return destination_attrs

    def create(self, validated_data: dict) -> BatchExport:
        """Create a BatchExport."""
        destination_data = validated_data.pop("destination")
        team_id = self.context["team_id"]
        model = validated_data["model"]
        hogql_query = validated_data.pop("hogql_query", None)
        hogql_modifiers = validated_data.pop("hogql_modifiers", None)

        source = None
        if model == BatchExport.Model.HOGQL:
            source = BatchExportSource(team_id=team_id, hogql_query=hogql_query, hogql_modifiers=hogql_modifiers)
        elif hogql_query is not None:
            # TODO: Migrate batch exports using a HogQL query to HogQL model.
            validated_data["schema"] = self.serialize_hogql_query_to_batch_export_schema(hogql_query)

        destination_views._set_default_parquet_extension(destination_data["type"], destination_data["config"])

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

    def _validate_hogql(self, attrs: dict[str, typing.Any]) -> None:
        """Validate the source of a batch export with the 'hogql' model.

        On update, a query or modifiers missing from the request keep the ones stored in the source.
        """
        if attrs.get("filters"):
            raise serializers.ValidationError({"filters": "'filters' are not supported when 'model' is 'hogql'"})

        team = self.context["get_team"]()
        check_hogql_batch_exports_enabled(team)

        source = self.instance.source if self.instance is not None else None
        hogql_query = attrs.get("hogql_query", source.hogql_query if source is not None else None)
        if not hogql_query:
            raise serializers.ValidationError({"hogql_query": "'hogql_query' is required when 'model' is 'hogql'"})

        try:
            modifiers = load_hogql_modifiers(
                attrs.get("hogql_modifiers", source.hogql_modifiers if source is not None else None)
            )
        except UnsupportedHogQLQueryError as e:
            raise serializers.ValidationError({"hogql_modifiers": str(e)}) from e

        user = self.context["request"].user
        try:
            validate_hogql_query_for_batch_export(hogql_query, team, user=user, modifiers=modifiers)
        except UnsupportedHogQLQueryError as e:
            raise serializers.ValidationError({"hogql_query": str(e)}) from e

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
        hogql_query_provided = "hogql_query" in validated_data
        hogql_query = validated_data.pop("hogql_query", None)
        hogql_modifiers_provided = "hogql_modifiers" in validated_data
        hogql_modifiers = validated_data.pop("hogql_modifiers", None)

        user = self.context["request"].user
        if not isinstance(user, User):
            raise NotAuthenticated()

        validated_data["last_modified_by"] = user

        with transaction.atomic():
            if destination_data:
                # Type changes are rejected by `validate_destination` — the incoming `type`
                # (if any) always equals the existing type by the time we get here.
                destination_views._pin_existing_parquet_extension(
                    batch_export.destination.type, batch_export.destination.config
                )
                batch_export.destination.config = recursive_dict_merge(
                    batch_export.destination.config,
                    destination_data.get("config", {}),
                )
                integration = destination_data.get("integration", batch_export.destination.integration)
                batch_export.destination.integration = integration

            if batch_export.model == BatchExport.Model.HOGQL:
                if hogql_query is not None or hogql_modifiers_provided:
                    source = batch_export.source or BatchExportSource(team_id=batch_export.team_id)
                    if hogql_query is not None:
                        source.hogql_query = hogql_query
                    if hogql_modifiers_provided:
                        source.hogql_modifiers = hogql_modifiers
                    source.save()
                    batch_export.source = source
            elif hogql_query is not None:
                validated_data["schema"] = self.serialize_hogql_query_to_batch_export_schema(hogql_query)
            elif hogql_query_provided:
                validated_data["schema"] = None

            batch_export.destination.save()
            batch_export = super().update(batch_export, validated_data)

            sync_batch_export(batch_export, created=False)

        return batch_export


def recursive_dict_merge(
    old: dict[str, typing.Any],
    new: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Merge two dictionaries, and recursively merge any dictionaries in them."""
    merged = {**old, **new}

    for key, value in merged.items():
        if not isinstance(value, dict):
            continue

        # Recurse only when both sides are dicts: a dict replacing a scalar (e.g. inline
        # credentials replacing an IAM role or an integration id) is an overwrite, not a merge.
        old_value = old.get(key)
        new_value = new.get(key)
        merged[key] = recursive_dict_merge(
            old_value if isinstance(old_value, dict) else {},
            new_value if isinstance(new_value, dict) else {},
        )

    return merged


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
        delete_batch_export(instance)

    @action(methods=["GET"], detail=False, required_scopes=["batch_export:read"])
    def test(self, request: request.Request, *args, **kwargs) -> response.Response:
        destination = request.query_params.get("destination", None)
        if not destination:
            return response.Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            destination_test = get_destination_test(destination=destination)
        except ValueError:
            return response.Response(status=status.HTTP_404_NOT_FOUND)

        return response.Response(destination_test.as_dict())

    @action(methods=["POST"], detail=False, required_scopes=["batch_export:write"])
    def run_test_step_new(self, request: request.Request, *args, **kwargs) -> response.Response:
        test_step = request.data.pop("step", 0)

        serializer = self.get_serializer(data=request.data)
        _ = serializer.is_valid(raise_exception=True)

        destination_test = get_destination_test(
            destination=serializer.validated_data["destination"]["type"],
        )
        test_configuration = serializer.validated_data["destination"]["config"]

        # if we have an integration, add its config and sensitive_config to test_configuration
        integration: Integration | None = serializer.validated_data["destination"].get("integration")
        if integration:
            test_configuration = {
                **test_configuration,
                **integration.config,
                **integration.sensitive_config,
                "integration": integration,
            }

        destination_test.configure(**test_configuration)

        result = destination_test.run_step(test_step)
        return response.Response(result.as_dict())

    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def run_test_step(self, request: request.Request, *args, **kwargs) -> response.Response:
        test_step = request.data.pop("step", 0)

        batch_export = self.get_object()

        # Remove any additional fields from stored configuration
        _, workflow_inputs = DESTINATION_WORKFLOWS[batch_export.destination.type]
        workflow_fields = {field.name for field in dataclasses.fields(BaseBatchExportInputs)} | {
            field.name for field in dataclasses.fields(workflow_inputs)
        }
        stored_config = {k: v for k, v in batch_export.destination.config.items() if k in workflow_fields}

        data = request.data
        data["destination"]["config"] = {**stored_config, **data["destination"]["config"]}

        serializer = self.get_serializer(data=data)
        _ = serializer.is_valid(raise_exception=True)

        destination_test = get_destination_test(
            destination=serializer.validated_data["destination"]["type"],
        )
        test_configuration = serializer.validated_data["destination"]["config"]

        # if we have an integration, add its config and sensitive_config to test_configuration
        integration: Integration | None = serializer.validated_data["destination"].get("integration")
        if integration:
            test_configuration = {
                **test_configuration,
                **integration.config,
                **integration.sensitive_config,
                "integration": integration,
            }

        destination_test.configure(**test_configuration)

        result = destination_test.run_step(test_step)
        return response.Response(result.as_dict())
