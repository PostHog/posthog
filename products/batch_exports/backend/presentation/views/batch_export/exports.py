"""Batch export endpoints: create, update, pause, unpause, delete and destination tests."""

import uuid
import typing
import dataclasses
from typing import cast

import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import request, response, serializers, status, viewsets
from rest_framework.exceptions import NotAuthenticated, NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import LimitOffsetPagination

from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.integrations import IntegrationRecord
from posthog.models import User

from products.batch_exports.backend.facade import (
    api as batch_exports_api,
    contracts,
)
from products.batch_exports.backend.facade.contracts import (
    BatchExportNotFoundError,
    BatchExportScheduleError,
    InvalidBatchExportDestinationError,
    InvalidBatchExportFilters,
    InvalidDestinationConfigError,
    UnsupportedDestinationTestError,
    UnsupportedHogQLQueryError,
)
from products.batch_exports.backend.facade.enums import (
    SUPPORTED_FILTER_TYPES_DISPLAY,
    TIMEZONES,
    BatchExportDestinationType,
    BatchExportInterval,
    BatchExportModel,
    IncrementalMode,
)
from products.batch_exports.backend.presentation.views.utils import (
    HOGQL_MODIFIERS_HELP_TEXT,
    HogQLModifiersField,
    check_high_frequency_batch_exports_enabled,
    check_hogql_batch_exports_enabled,
    fetch_facade_page,
    parse_path_uuid,
)

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


def _get_integration_id(destination_attrs: dict[str, typing.Any]) -> int | None:
    """Return the id of the integration a request sent, or None when it sent none or null."""
    integration: IntegrationRecord | None = destination_attrs.get("integration")
    return integration.id if integration is not None else None


def _get_integration_change(destination_attrs: dict[str, typing.Any]) -> contracts.IntegrationChange | None:
    """Return the integration change a request asks for, or None when it left the integration out."""
    if "integration" not in destination_attrs:
        return None
    return contracts.IntegrationChange(integration_id=_get_integration_id(destination_attrs))


class BatchExportSerializer(serializers.Serializer):
    """Serializer for a BatchExport model."""

    id = serializers.UUIDField(read_only=True)
    team_id = serializers.IntegerField(read_only=True, help_text="The team this belongs to.")
    name = serializers.CharField(
        help_text="A human-readable name for this BatchExport.", style={"base_template": "textarea.html"}
    )
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
    interval = serializers.ChoiceField(
        choices=BatchExportInterval.choices,
        help_text="How often the batch export should run.",
    )
    paused = serializers.BooleanField(required=False, help_text="Whether this BatchExport is paused or not.")
    created_at = serializers.DateTimeField(
        read_only=True, help_text="The timestamp at which this BatchExport was created."
    )
    last_updated_at = serializers.DateTimeField(
        read_only=True, help_text="The timestamp at which this BatchExport was last updated."
    )
    last_paused_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="The timestamp at which this BatchExport was last paused."
    )
    start_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Time before which any Batch Export runs won't be triggered."
    )
    end_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Time after which any Batch Export runs won't be triggered."
    )
    latest_runs = run_views.BatchExportRunSerializer(
        many=True,
        read_only=True,
        help_text="The 10 most recent runs of this batch export, ordered newest first.",
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
    schema = serializers.JSONField(read_only=True, help_text="A schema of custom fields to select when exporting data.")
    filters = serializers.JSONField(required=False, allow_null=True)
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
        # Saving the export checks the query, when it builds the schema the export stores.
        if model == BatchExportModel.EVENTS and attrs.get("hogql_query") is not None:
            is_grandfathered_organization = batch_exports_api.organization_has_custom_events_schema_exports(
                self.context["get_team"]().organization_id
            )
            if not is_grandfathered_organization:
                self._validate_attribute_only_supported_for_model(
                    attrs, name="hogql_query", model=BatchExportModel.HOGQL
                )
        else:
            self._validate_attribute_only_supported_for_model(attrs, name="hogql_query", model=BatchExportModel.HOGQL)

        if model == BatchExportModel.HOGQL:
            self._validate_hogql_query(attrs)

        return attrs

    def _validate_interval_offset(self, attrs: dict) -> dict:
        # Check if offset fields are in the request (for PATCH, distinguish between absent and None)
        offset_day_provided = "offset_day" in attrs
        offset_hour_provided = "offset_hour" in attrs

        # Convert offset_day and offset_hour to interval_offset
        if "interval" in attrs:
            interval = attrs["interval"]
            offset_day = attrs.pop("offset_day", None)
            offset_hour = attrs.pop("offset_hour", None)
        elif self.instance is not None and (offset_day_provided or offset_hour_provided):
            # A PATCH may send offsets alone. They apply to the saved interval, and an offset the
            # PATCH leaves out keeps its saved value.
            interval = self.instance.interval
            offset_day = attrs.pop("offset_day", self.instance.offset_day)
            offset_hour = attrs.pop("offset_hour", self.instance.offset_hour)
        else:
            return attrs

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

        def get_value(name: str) -> typing.Any:
            """Return the value the request sent, or else the saved one."""
            return attrs.get(name, getattr(self.instance, name, None))

        hogql_query = get_value("hogql_query")
        if hogql_query is None:
            raise serializers.ValidationError({"hogql_query": "'hogql_query' is required when 'model' is 'hogql'"})

        # Saved modifiers are valid, even if the query check re-validates them anyways.
        hogql_modifiers = get_value("hogql_modifiers")
        try:
            output_columns = set(
                batch_exports_api.validate_hogql_query(
                    self.context["team_id"],
                    user_id=self._get_user().pk,
                    hogql_query=hogql_query,
                    hogql_modifiers=hogql_modifiers,
                )
            )
        except UnsupportedHogQLQueryError as e:
            raise serializers.ValidationError({"hogql_query": str(e)}) from e

        incremental_mode = get_value("incremental_mode")
        primary_key = set(get_value("primary_key") or ())

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

        version_key = set(get_value("version_key") or ())
        missing_version_key = version_key - output_columns

        if missing_version_key:
            raise serializers.ValidationError(
                {
                    "version_key": f"'version_key' contains columns that are not present in the query: {','.join(missing_version_key)}"
                }
            )

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

        try:
            batch_exports_api.validate_batch_export_destination(
                self.context["team_id"],
                export_id=export_id,
                destination_type=destination_type,
                config=destination_attrs["config"],
                integration=_get_integration_change(destination_attrs),
            )
        except InvalidBatchExportDestinationError as e:
            raise serializers.ValidationError(str(e))
        except BatchExportNotFoundError:
            raise NotFound(f"BatchExport ID '{export_id}' not found.")

        if destination_type == BatchExportDestinationType.WORKFLOWS:
            team = self.context["get_team"]()

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

    def _get_user(self) -> User:
        user = self.context["request"].user
        if not isinstance(user, User):
            raise NotAuthenticated()
        return user

    def create(self, validated_data: dict) -> contracts.BatchExportConfiguration:
        """Create a BatchExport."""
        destination_data = validated_data["destination"]
        export = contracts.NewBatchExport(
            destination=contracts.BatchExportDestinationInput(
                type=destination_data["type"],
                config=destination_data["config"],
                integration_id=_get_integration_id(destination_data),
            ),
            **{name: value for name, value in validated_data.items() if name != "destination"},
        )
        try:
            return batch_exports_api.create_batch_export_from_input(
                self.context["team_id"], user_id=self._get_user().pk, export=export
            )
        except UnsupportedHogQLQueryError as e:
            raise serializers.ValidationError(str(e))

    def update(
        self, instance: contracts.BatchExportConfiguration, validated_data: dict
    ) -> contracts.BatchExportConfiguration:
        """Update a BatchExport."""
        user = self._get_user()
        destination_data = validated_data.pop("destination", None)
        # The model cannot change, as `validate_model` checks.
        validated_data.pop("model", None)

        destination = None
        if destination_data:
            destination = contracts.BatchExportDestinationPatch(
                config=destination_data.get("config", {}),
                integration=_get_integration_change(destination_data),
            )

        update = contracts.BatchExportUpdate(
            changed=frozenset(validated_data),
            destination=destination,
            **validated_data,
        )
        try:
            return batch_exports_api.update_batch_export(
                self.context["team_id"], instance.id, user_id=user.pk, update=update
            )
        except UnsupportedHogQLQueryError as e:
            raise serializers.ValidationError(str(e))


# The viewset has no queryset to type the `id` path parameter from, so each detail action declares it.
BATCH_EXPORT_ID_PARAMETER = OpenApiParameter(
    "id", OpenApiTypes.UUID, OpenApiParameter.PATH, description="A UUID string identifying this batch export."
)


@extend_schema(tags=["batch_exports"])
@extend_schema_view(
    # Request bodies use a polymorphic destination schema so that integration-backed types
    # (Databricks, AzureBlob, BigQuery, Postgres, AwsS3, S3Compatible, Snowflake, Redshift) advertise
    # integration_id up front. It is required for every one of them; Postgres and Redshift exports
    # created before integrations keep their inline credentials on update.
    # Responses continue to use BatchExportSerializer.
    create=extend_schema(request=BatchExportRequestSerializer),
    update=extend_schema(request=BatchExportRequestSerializer, parameters=[BATCH_EXPORT_ID_PARAMETER]),
    partial_update=extend_schema(request=BatchExportRequestSerializer, parameters=[BATCH_EXPORT_ID_PARAMETER]),
    retrieve=extend_schema(parameters=[BATCH_EXPORT_ID_PARAMETER]),
    destroy=extend_schema(parameters=[BATCH_EXPORT_ID_PARAMETER]),
    logs=extend_schema(parameters=[BATCH_EXPORT_ID_PARAMETER]),
)
class BatchExportViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, viewsets.ModelViewSet):
    scope_object = "batch_export"
    serializer_class = BatchExportSerializer
    log_source = "batch_exports"

    def dangerously_get_object(self) -> contracts.BatchExportConfiguration:
        # The mixin's get_object() reads through a queryset, which this view does not have, so the
        # export is read through the facade instead. That skips the mixin's team filter and object
        # permission check, so both happen here: the facade filters by team, and
        # check_object_permissions runs on the contract. `logs` reads the export through here too.
        export_id = parse_path_uuid(self.kwargs["pk"])
        try:
            batch_export = batch_exports_api.get_batch_export(
                self.team_id, export_id, include_latest_runs=self.action == "retrieve"
            )
        except BatchExportNotFoundError as e:
            raise NotFound(*e.args) from e
        self.check_object_permissions(self.request, batch_export)
        return batch_export

    def list(self, request: request.Request, *args: typing.Any, **kwargs: typing.Any) -> response.Response:
        paginator = cast(LimitOffsetPagination, self.paginator)
        batch_exports = fetch_facade_page(
            paginator,
            request,
            lambda offset, limit: batch_exports_api.list_batch_exports(self.team_id, offset=offset, limit=limit),
        )
        return paginator.get_paginated_response(self.get_serializer(batch_exports, many=True).data)

    @extend_schema(request=None, parameters=[BATCH_EXPORT_ID_PARAMETER])
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

    @extend_schema(request=BatchExportUnpauseRequestSerializer, parameters=[BATCH_EXPORT_ID_PARAMETER])
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

    def perform_destroy(self, instance: contracts.BatchExportConfiguration) -> None:
        """Perform a BatchExport destroy by clearing Temporal and Django state.

        If the underlying Temporal Schedule doesn't exist, we ignore the error and proceed with the delete anyways.
        The Schedule could have been manually deleted causing Django and Temporal to go out of sync. For whatever reason,
        since we are deleting, we assume that we can recover from this state by finishing the delete operation.
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

    def _run_destination_test_step(
        self, serializer: serializers.BaseSerializer, step: int, *, export_id: uuid.UUID | None
    ) -> response.Response:
        destination = serializer.validated_data["destination"]
        try:
            result = batch_exports_api.run_destination_test_step(
                self.team_id,
                export_id=export_id,
                destination_type=destination["type"],
                config=destination["config"],
                integration_id=_get_integration_id(destination),
                step=step,
            )
        except UnsupportedDestinationTestError:
            raise ValidationError(f"Connection tests aren't available for {destination['type']} destinations.")
        except InvalidDestinationConfigError as e:
            raise ValidationError(str(e))
        except BatchExportNotFoundError:
            raise NotFound(f"BatchExport ID '{export_id}' not found.")
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

        return self._run_destination_test_step(serializer, test_step, export_id=None)

    @extend_schema(parameters=[BATCH_EXPORT_ID_PARAMETER])
    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def run_test_step(self, request: request.Request, *args, **kwargs) -> response.Response:
        test_step = self._parse_destination_test_step(request)

        batch_export = self.get_object()
        serializer = self.get_serializer(
            data=request.data, context={**self.get_serializer_context(), "partial_destination_config": True}
        )
        _ = serializer.is_valid(raise_exception=True)

        return self._run_destination_test_step(serializer, test_step, export_id=batch_export.id)
