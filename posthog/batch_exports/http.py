import typing
import builtins
import datetime as dt
import dataclasses
import collections.abc
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from django.db import transaction
from django.utils.timezone import now

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import filters, mixins, request, response, serializers, status, viewsets
from rest_framework.exceptions import NotAuthenticated, NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import CursorPagination

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast, errors
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast

from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.batch_exports.models import BATCH_EXPORT_INTERVALS, TIMEZONES
from posthog.batch_exports.service import (
    DESTINATION_WORKFLOWS,
    BaseBatchExportInputs,
    BatchExportIdError,
    BatchExportSchema,
    BatchExportServiceError,
    BatchExportServiceRPCError,
    BatchExportWithNoEndNotAllowedError,
    backfill_export,
    cancel_running_batch_export_run,
    delete_batch_export,
    fetch_earliest_backfill_start_at,
    pause_batch_export,
    sync_batch_export,
    sync_cancel_running_batch_export_backfill,
    unpause_batch_export,
)
from posthog.models import BatchExport, BatchExportBackfill, BatchExportDestination, BatchExportRun, Team, User
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.integration import (
    AzureBlobIntegration,
    AzureBlobIntegrationError,
    DatabricksIntegration,
    DatabricksIntegrationError,
    Integration,
)
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.temporal.common.client import sync_connect
from posthog.utils import relative_date_parse, str_to_bool

from products.batch_exports.backend.api.destination_tests import get_destination_test
from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import (
    SUPPORTED_COMPRESSIONS as AZURE_BLOB_SUPPORTED_COMPRESSIONS,
)
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    SUPPORTED_COMPRESSIONS as S3_SUPPORTED_COMPRESSIONS,
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


class BatchExportRunSerializer(serializers.ModelSerializer):
    """Serializer for a BatchExportRun model."""

    class Meta:
        model = BatchExportRun
        fields = "__all__"
        # TODO: Why aren't all these read only?
        read_only_fields = ["batch_export"]


class RunsCursorPagination(CursorPagination):
    page_size = 100


@extend_schema(tags=["batch_exports"])
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

    integration_id = serializers.PrimaryKeyRelatedField(
        write_only=True, queryset=Integration.objects.all(), source="integration", required=False, allow_null=True
    )

    class Meta:
        model = BatchExportDestination
        fields = ["type", "config", "integration", "integration_id"]

    def create(self, validated_data: collections.abc.Mapping[str, typing.Any]) -> BatchExportDestination:
        """Create a BatchExportDestination."""
        export_destination = BatchExportDestination.objects.create(**validated_data)
        return export_destination

    def validate(self, data: collections.abc.Mapping[str, typing.Any]) -> collections.abc.Mapping[str, typing.Any]:
        """Validate the destination configuration based on workflow inputs.

        Ensure that the submitted destination configuration passes the following checks:
        * Does NOT contain fields that do not exist in workflow inputs.
        * Contains all required fields as defined by workflow inputs.
        * Provided values match types required by workflow inputs.

        Raises:
            A `serializers.ValidationError` if any of these checks fail.
        """
        export_type, config = data["type"], data["config"]
        _, workflow_inputs = DESTINATION_WORKFLOWS[export_type]
        base_field_names = {field.name for field in dataclasses.fields(BaseBatchExportInputs)}
        workflow_fields = dataclasses.fields(workflow_inputs)
        destination_fields = {field for field in workflow_fields if field.name not in base_field_names}

        extra_fields = config.keys() - {field.name for field in destination_fields} - base_field_names
        if extra_fields:
            str_fields = ", ".join(f"'{extra_field}'" for extra_field in sorted(extra_fields))
            raise serializers.ValidationError(f"Configuration has unknown field/s: {str_fields}")

        for destination_field in destination_fields:
            is_required = (
                destination_field.default == dataclasses.MISSING
                and destination_field.default_factory == dataclasses.MISSING
            )
            if destination_field.name not in config:
                is_patch = self.context["request"].method == "PATCH"
                if is_required and not is_patch:
                    # When patching we expect a partial configuration. So, we don't
                    # error on missing required fields.
                    raise serializers.ValidationError(
                        f"Configuration missing required field: '{destination_field.name}'"
                    )
                else:
                    continue

            config_value = config[destination_field.name]
            field_type = destination_field.type

            if not isinstance(field_type, type):
                # `dataclasses.Field.type` could be something we can't work with.
                # TODO: Validate these ones too?
                continue

            if not isinstance(config_value, field_type):
                config_value, success = try_convert_to_type(config_value, field_type)

                if not success:
                    raise serializers.ValidationError(
                        f"Configuration has invalid type: got '{type(config_value).__name__}', expected '{field_type.__name__}'"
                    )

                config[destination_field.name] = config_value

        return data

    def to_representation(self, instance: BatchExportDestination) -> dict:
        data = super().to_representation(instance)

        def remove_secret_fields_recursive(d: dict[str, typing.Any]):
            target = {}

            for k, v in d.items():
                if k in BatchExportDestination.secret_fields[instance.type]:
                    continue
                elif isinstance(v, dict):
                    target[k] = remove_secret_fields_recursive(v)
                else:
                    target[k] = v

            return target

        data["config"] = remove_secret_fields_recursive(data["config"])

        return data


Success = bool


def try_convert_to_type(value: typing.Any, target_type: type) -> tuple[typing.Any, Success]:
    """Attempt to convert value to target type based on well-known casting functions.

    This doesn't raise any exceptions but rather returns a tuple with a bool indicating
    if the value in the first position was successfully casted to `target_type` or not.
    If casting fails, the value in the first position is returned unchanged, otherwise a
    new value of type `target_type` is returned.
    """
    current_type = type(value)

    match (current_type, target_type):
        case (builtins.str, builtins.bool):
            cast_func: typing.Callable[[typing.Any], typing.Any] = str_to_bool
        case (builtins.str, builtins.int):
            cast_func = int
        case _:
            return (value, False)

    try:
        new_value = cast_func(value)
    except Exception:
        return (value, False)

    return (new_value, True)


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
    timezone = serializers.ChoiceField(choices=TIMEZONES, required=False, allow_null=True)
    offset_day = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=6)
    offset_hour = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=23)

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

        return attrs

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
        if filters is None:
            return filters

        if not isinstance(filters, list):
            raise serializers.ValidationError("'filters' should be an array of filters")

        for filter in filters:
            if isinstance(filter, dict) and any(key in filter for key in ("data_interval_start", "data_interval_end")):
                raise serializers.ValidationError(
                    "'data_interval_start' and 'data_interval_end' are run attributes and not 'filters'."
                    " Trigger a backfill if you wish to manually control which periods to batch export."
                )
        return filters

    # TODO: could this be moved inside BatchExportDestinationSerializer::validate?
    def validate_destination(self, destination_attrs: dict):
        destination_type = destination_attrs["type"]
        config = destination_attrs["config"]
        view = self.context.get("view")

        if self.instance is not None:
            existing_config = self.instance.destination.config
        elif view is not None and "pk" in view.kwargs:
            # Running validation for a `detail=True` action.
            instance = view.get_object()
            existing_config = instance.destination.config
        else:
            existing_config = {}
        merged_config = recursive_dict_merge(existing_config, config)

        # SSRF protection for HTTP batch exports
        if destination_type == BatchExportDestination.Destination.HTTP:
            url = merged_config.get("url")
            if url and url not in ("https://us.i.posthog.com/batch/", "https://eu.i.posthog.com/batch/"):
                raise serializers.ValidationError(f"Invalid destination URL: {url}")

        if destination_type == BatchExportDestination.Destination.SNOWFLAKE:
            if config.get("authentication_type") == "password" and merged_config.get("password") is None:
                raise serializers.ValidationError("Password is required if authentication type is password")
            if config.get("authentication_type") == "keypair" and merged_config.get("private_key") is None:
                raise serializers.ValidationError("Private key is required if authentication type is key pair")

        if destination_type == BatchExportDestination.Destination.S3:
            # we already validate the required inputs in BatchExportDestinationSerializer::validate
            # so here we just ensure that the inputs are not empty
            required_non_empty_inputs = (
                "bucket_name",
                "region",
                "prefix",
                "aws_access_key_id",
                "aws_secret_access_key",
            )
            empty_inputs = []
            for required_input in required_non_empty_inputs:
                value = config.get(required_input)
                if value is not None and isinstance(value, str) and value.strip() == "":
                    empty_inputs.append(required_input)
            if empty_inputs:
                raise serializers.ValidationError(f"The following inputs are empty: {empty_inputs}")

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

            # if someone is trying to reset the endpoint url, then we need to convert empty string to None
            if merged_config.get("endpoint_url") == "":
                destination_attrs["config"]["endpoint_url"] = None

        if destination_type == BatchExportDestination.Destination.DATABRICKS:
            team_id = self.context["team_id"]
            team = Team.objects.get(id=team_id)

            if not posthoganalytics.feature_enabled(
                "databricks-batch-exports",
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
                raise PermissionDenied("The Databricks destination is not enabled for this team.")

            # validate the Integration is valid (this is mandatory for Databricks batch exports)
            integration: Integration | None = destination_attrs.get("integration")
            if integration is None:
                raise serializers.ValidationError("Integration is required for Databricks batch exports")
            if integration.team_id != team_id:
                raise serializers.ValidationError("Integration does not belong to this team.")
            if integration.kind != Integration.IntegrationKind.DATABRICKS:
                raise serializers.ValidationError("Integration is not a Databricks integration.")
            # try instantiate the integration to check if it's valid
            try:
                DatabricksIntegration(integration)
            except DatabricksIntegrationError as e:
                raise serializers.ValidationError(str(e))

        if destination_type == BatchExportDestination.Destination.AZURE_BLOB:
            team_id = self.context["team_id"]
            team = Team.objects.get(id=team_id)

            if not posthoganalytics.feature_enabled(
                "azure-blob-batch-exports",
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
                raise PermissionDenied("Azure Blob Storage batch exports are not enabled for this team.")

            # validate the Integration is valid (this is mandatory for Azure Blob batch exports)
            integration = destination_attrs.get("integration")
            if integration is None:
                raise serializers.ValidationError("Integration is required for Azure Blob batch exports")
            if integration.team_id != team_id:
                raise serializers.ValidationError("Integration does not belong to this team.")
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
            mode = merged_config.get("mode")

            if mode == "COPY":
                copy_inputs = merged_config.get("copy_inputs", {})
                if not copy_inputs:
                    raise serializers.ValidationError("Missing required inputs for 'COPY'")

                required_inputs = {"s3_bucket", "region_name", "authorization", "bucket_credentials"}
                if required_inputs - copy_inputs.keys():
                    raise serializers.ValidationError("Missing required input for 'COPY'")

                credential_keys = {"aws_access_key_id", "aws_secret_access_key"}
                if credential_keys - copy_inputs["bucket_credentials"].keys():
                    raise serializers.ValidationError("Missing required bucket credentials for 'COPY'")

                authorization = copy_inputs.get("authorization")
                if isinstance(authorization, dict):
                    if credential_keys - authorization.keys():
                        raise serializers.ValidationError("Missing required credentials for 'COPY'")
                elif isinstance(authorization, str) and not authorization.strip():
                    raise serializers.ValidationError("Missing required IAM role for 'COPY'")

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

        if isinstance(parsed.select_from.table, ast.SelectQuery):
            raise serializers.ValidationError("Subqueries or CTEs are not supported")

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
                batch_export.destination.config = recursive_dict_merge(
                    batch_export.destination.config,
                    destination_data.get("config", {}),
                )
                integration = destination_data.get("integration", batch_export.destination.integration)
                batch_export.destination.integration = integration

            if hogql_query := validated_data.pop("hogql_query", None):
                batch_export_schema = self.serialize_hogql_query_to_batch_export_schema(hogql_query)
                validated_data["schema"] = batch_export_schema

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

        merged[key] = recursive_dict_merge(old.get(key, None) or {}, new.get(key, None) or {})

    return merged


@extend_schema(tags=["batch_exports"])
class BatchExportViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, viewsets.ModelViewSet):
    scope_object = "batch_export"
    queryset = BatchExport.objects.exclude(deleted=True).order_by("-created_at").prefetch_related("destination").all()
    serializer_class = BatchExportSerializer
    log_source = "batch_exports"

    def safely_get_queryset(self, queryset):
        """Filter out batch exports with Workflows destination type if action is list."""
        if self.action == "list":
            return queryset.exclude(destination__type="Workflows")
        return queryset

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
        delete_batch_export(instance)

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

        # if we have an integration, add its config and sensitive_config to test_configuration
        integration: Integration | None = serializer.validated_data["destination"].get("integration")
        if integration:
            test_configuration = {**test_configuration, **integration.config, **integration.sensitive_config}

        destination_test.configure(**test_configuration)

        result = destination_test.run_step(test_step)
        return response.Response(result.as_dict())

    @action(methods=["POST"], detail=True, required_scopes=["INTERNAL"])
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
            test_configuration = {**test_configuration, **integration.config, **integration.sensitive_config}

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
        start_at = validate_date_input(start_at_input, batch_export)
    else:
        start_at = None

    if end_at_input is not None:
        end_at = validate_date_input(end_at_input, batch_export)
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
        raise ValidationError("The initial backfill datetime 'start_at' must be before 'end_at'")
    if end_at > dt.datetime.now(dt.UTC):
        raise ValidationError(f"The provided 'end_at' ({end_at.isoformat()}) is in the future")

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


@dataclasses.dataclass(frozen=True)
class BatchExportContext(ActivityContextBase):
    name: str
    destination_type: str
    interval: str
    created_by_user_id: str | None
    created_by_user_email: str | None
    created_by_user_name: str | None


@mutable_receiver(model_activity_signal, sender=BatchExport)
def handle_batch_export_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    from posthog.models.activity_logging.batch_export_utils import (
        get_batch_export_created_by_info,
        get_batch_export_destination_type,
        get_batch_export_detail_name,
    )

    # Use after_update for create/update, before_update for delete
    batch_export = after_update or before_update

    if not batch_export:
        return

    destination_type = get_batch_export_destination_type(batch_export)
    created_by_user_id, created_by_user_email, created_by_user_name = get_batch_export_created_by_info(batch_export)
    detail_name = get_batch_export_detail_name(batch_export, destination_type)

    context = BatchExportContext(
        name=batch_export.name or "Unnamed Export",
        destination_type=destination_type,
        interval=batch_export.interval or "",
        created_by_user_id=created_by_user_id,
        created_by_user_email=created_by_user_email,
        created_by_user_name=created_by_user_name,
    )

    log_activity(
        organization_id=batch_export.team.organization_id,
        team_id=batch_export.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=batch_export.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )
