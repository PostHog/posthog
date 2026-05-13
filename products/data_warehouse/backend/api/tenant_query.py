from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.data_warehouse.backend.tenant_query import (
    MAX_TENANT_QUERY_OBSERVABILITY_LIMIT,
    configure_tenant_query,
    execute_tenant_query,
    get_tenant_query_config,
    get_tenant_query_execution,
    list_tenant_query_executions,
    summarize_tenant_query_errors,
    summarize_tenant_query_usage,
)


@extend_schema_field(
    {
        "oneOf": [{"type": "string"}, {"type": "integer"}],
        "nullable": True,
        "description": "Tenant value to enforce against the configured tenant column.",
    }
)
class TenantValueField(serializers.Field):
    default_error_messages = {"invalid": "Tenant value must be a string, UUID, or integer."}

    def to_internal_value(self, data: object) -> object:
        if data is None or isinstance(data, str):
            return data
        if isinstance(data, int) and not isinstance(data, bool):
            return data
        self.fail("invalid")

    def to_representation(self, value: object) -> object:
        return value


@extend_schema_field(
    {
        "oneOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "integer"},
            {"type": "boolean"},
            {"type": "object"},
            {"type": "array", "items": {}},
        ],
        "nullable": True,
        "description": "One result cell returned by the tenant-scoped query.",
    }
)
class TenantQueryResultValueField(serializers.JSONField):
    pass


class TenantQueryTimingSerializer(serializers.Serializer):
    k = serializers.CharField(help_text="Timing key.")
    t = serializers.FloatField(help_text="Elapsed time in seconds.")


class TenantQueryRequestSerializer(serializers.Serializer):
    connection_id = serializers.UUIDField(help_text="Direct Postgres connection ID to query.")
    tenant_value = TenantValueField(
        required=False,
        allow_null=True,
        help_text="Tenant value to enforce against the configured tenant column.",
    )
    query = serializers.CharField(help_text="HogQL SELECT query to execute against the tenant-scoped connection.")
    timeout_ms = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Optional statement timeout in milliseconds, capped by the connection tenant-query config.",
    )


class TenantQueryConfigRequestSerializer(serializers.Serializer):
    connection_id = serializers.UUIDField(help_text="Direct Postgres connection ID to configure.")
    enabled = serializers.BooleanField(help_text="Whether tenant-scoped querying is enabled for this connection.")
    tenant_column_name = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        help_text="Column name that must exist on every enabled table and will be enforced as the tenant key.",
    )
    tenant_column_names_by_table = serializers.DictField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        help_text=(
            "Optional per-table tenant column overrides keyed by direct Postgres table name. Each override must have "
            "the same inferred tenant type as the global tenant column."
        ),
    )
    default_timeout_ms = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Default statement timeout in milliseconds when a request does not provide timeout_ms.",
    )
    max_timeout_ms = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Maximum allowed statement timeout in milliseconds.",
    )
    max_result_limit = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Maximum result row limit. Explicit query limits above this value are clamped.",
    )

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        default_timeout_ms = attrs.get("default_timeout_ms")
        max_timeout_ms = attrs.get("max_timeout_ms")
        if isinstance(default_timeout_ms, int) and isinstance(max_timeout_ms, int):
            if default_timeout_ms > max_timeout_ms:
                raise serializers.ValidationError("default_timeout_ms must be less than or equal to max_timeout_ms.")
        return attrs


class TenantQueryConfigLoadRequestSerializer(serializers.Serializer):
    connection_id = serializers.UUIDField(help_text="Direct Postgres connection ID to inspect.")


class TenantQueryConfigResponseSerializer(serializers.Serializer):
    connection_id = serializers.UUIDField(help_text="Direct Postgres connection ID.")
    enabled = serializers.BooleanField(help_text="Whether tenant-scoped querying is enabled for this connection.")
    tenant_column_name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Configured tenant column name.",
    )
    tenant_column_type = serializers.ChoiceField(
        choices=["integer", "string", "uuid"],
        required=False,
        allow_null=True,
        help_text="Tenant column type inferred from direct Postgres schema metadata.",
    )
    tenant_column_names_by_table = serializers.DictField(
        child=serializers.CharField(),
        help_text="Per-table tenant column overrides keyed by direct Postgres table name.",
    )
    default_timeout_ms = serializers.IntegerField(help_text="Default statement timeout in milliseconds.")
    max_timeout_ms = serializers.IntegerField(help_text="Maximum allowed statement timeout in milliseconds.")
    max_result_limit = serializers.IntegerField(help_text="Maximum result row limit.")
    enabled_tables = serializers.ListField(
        child=serializers.CharField(),
        help_text="Enabled direct Postgres tables available to tenant-scoped queries.",
    )
    disabled_tables = serializers.ListField(
        child=serializers.CharField(),
        help_text="Previously enabled tables disabled during configuration because they lacked the tenant column.",
    )


class TenantQueryResponseSerializer(serializers.Serializer):
    query = serializers.CharField(required=False, allow_null=True, help_text="Original query string.")
    hogql = serializers.CharField(required=False, allow_null=True, help_text="Prepared HogQL query.")
    postgres_sql = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Prepared SQL executed against the direct Postgres connection.",
    )
    error = serializers.CharField(
        required=False, allow_null=True, help_text="Execution error, when debug mode is used."
    )
    hasMore = serializers.BooleanField(required=False, help_text="Whether the query has more rows available.")
    limit = serializers.IntegerField(required=False, help_text="Effective result limit.")
    offset = serializers.IntegerField(required=False, help_text="Effective result offset.")
    timings = TenantQueryTimingSerializer(many=True, required=False, help_text="HogQL execution timing entries.")
    results = serializers.ListField(
        child=serializers.ListField(child=TenantQueryResultValueField()),
        required=False,
        help_text="Result rows.",
    )
    columns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Result column names.",
    )
    types = serializers.ListField(
        child=serializers.ListField(child=serializers.CharField()),
        required=False,
        help_text="Result column type metadata.",
    )


class TenantQueryObservabilityRequestSerializer(serializers.Serializer):
    connection_id = serializers.UUIDField(
        required=False,
        help_text="Optional direct Postgres connection ID to filter executions.",
    )
    tenant_value = TenantValueField(
        required=False,
        allow_null=True,
        help_text="Optional tenant value to filter executions.",
    )
    date_from = serializers.DateTimeField(
        required=False,
        help_text="Start timestamp for the execution log search. Defaults to 24 hours before date_to.",
    )
    date_to = serializers.DateTimeField(
        required=False,
        help_text="End timestamp for the execution log search. Defaults to now.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
        max_value=MAX_TENANT_QUERY_OBSERVABILITY_LIMIT,
        help_text="Maximum number of executions or summary rows to return.",
    )


class TenantQueryExecutionsRequestSerializer(TenantQueryObservabilityRequestSerializer):
    success = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Optional success status to filter executions.",
    )


class TenantQueryExecutionDetailRequestSerializer(serializers.Serializer):
    execution_id = serializers.CharField(help_text="Execution log UUID returned by the executions list.")
    timestamp = serializers.DateTimeField(
        required=False,
        help_text="Optional execution timestamp to narrow the Logs search window.",
    )


@extend_schema_field(
    {
        "oneOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "integer"},
            {"type": "boolean"},
            {"type": "object"},
            {"type": "array", "items": {}},
        ],
        "nullable": True,
        "description": "Structured tenant query execution log value.",
    }
)
class TenantQueryJSONValueField(serializers.JSONField):
    pass


class TenantQueryExecutionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Execution log UUID.")
    timestamp = serializers.DateTimeField(allow_null=True, help_text="Execution log timestamp.")
    connection_id = serializers.CharField(help_text="Direct Postgres connection ID.")
    tenant_value = serializers.CharField(help_text="Tenant value enforced for the query.")
    original_query = serializers.CharField(help_text="Original HogQL query submitted to the tenant query service.")
    postgres_sql = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Prepared SQL executed against the direct Postgres connection.",
    )
    success = serializers.BooleanField(help_text="Whether the execution completed successfully.")
    error = serializers.CharField(required=False, allow_null=True, help_text="Execution error message, when present.")
    duration_ms = serializers.FloatField(
        required=False, allow_null=True, help_text="Execution duration in milliseconds."
    )
    row_count = serializers.IntegerField(required=False, allow_null=True, help_text="Number of result rows returned.")
    referenced_tables = serializers.ListField(
        child=serializers.CharField(),
        help_text="Direct Postgres tables referenced by the query.",
    )
    metadata_only = serializers.BooleanField(help_text="Whether the request was served from metadata system tables.")


class TenantQueryExecutionDetailSerializer(TenantQueryExecutionSerializer):
    referenced_table_metadata = serializers.ListField(
        child=serializers.DictField(child=TenantQueryJSONValueField()),
        required=False,
        help_text="Postgres table metadata captured for referenced tables.",
    )
    connection_metadata = serializers.DictField(
        child=TenantQueryJSONValueField(),
        required=False,
        help_text="Direct Postgres connection metadata captured at execution time.",
    )
    attributes = serializers.DictField(
        child=TenantQueryJSONValueField(),
        required=False,
        help_text="Raw structured log attributes for this execution.",
    )


class TenantQueryExecutionsResponseSerializer(serializers.Serializer):
    executions = TenantQueryExecutionSerializer(many=True, help_text="Tenant query executions.")
    count = serializers.IntegerField(help_text="Number of executions returned.")


class TenantQueryExecutionDetailResponseSerializer(serializers.Serializer):
    execution = TenantQueryExecutionDetailSerializer(help_text="Tenant query execution detail.")


class TenantQueryErrorSummarySerializer(serializers.Serializer):
    connection_id = serializers.CharField(help_text="Direct Postgres connection ID.")
    tenant_value = serializers.CharField(help_text="Tenant value enforced for the failed query.")
    referenced_tables = serializers.ListField(
        child=serializers.CharField(),
        help_text="Direct Postgres tables referenced by the failed query.",
    )
    original_query = serializers.CharField(help_text="Original HogQL query submitted to the tenant query service.")
    error = serializers.CharField(help_text="Execution error message.")
    count = serializers.IntegerField(help_text="Number of matching failed executions.")
    last_seen_at = serializers.DateTimeField(allow_null=True, help_text="Most recent matching failure timestamp.")
    average_duration_ms = serializers.FloatField(
        allow_null=True,
        help_text="Average failed execution duration in milliseconds.",
    )


class TenantQueryErrorSummaryResponseSerializer(serializers.Serializer):
    errors = TenantQueryErrorSummarySerializer(many=True, help_text="Grouped tenant query execution errors.")
    count = serializers.IntegerField(help_text="Number of groups returned.")


class TenantQueryUsageSummarySerializer(serializers.Serializer):
    connection_id = serializers.CharField(help_text="Direct Postgres connection ID.")
    tenant_value = serializers.CharField(help_text="Tenant value enforced for the query group.")
    referenced_tables = serializers.ListField(
        child=serializers.CharField(),
        help_text="Direct Postgres tables referenced by the query group.",
    )
    count = serializers.IntegerField(help_text="Total matching executions.")
    success_count = serializers.IntegerField(help_text="Number of successful executions.")
    error_count = serializers.IntegerField(help_text="Number of failed executions.")
    total_rows = serializers.IntegerField(help_text="Total result rows returned by matching executions.")
    average_duration_ms = serializers.FloatField(
        allow_null=True,
        help_text="Average execution duration in milliseconds.",
    )
    last_seen_at = serializers.DateTimeField(allow_null=True, help_text="Most recent matching execution timestamp.")


class TenantQueryUsageSummaryResponseSerializer(serializers.Serializer):
    usage = TenantQueryUsageSummarySerializer(many=True, help_text="Grouped tenant query execution usage.")
    count = serializers.IntegerField(help_text="Number of groups returned.")


class TenantQueryViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    serializer_class = TenantQueryRequestSerializer
    scope_object = "query"
    scope_object_read_actions = ["create", "config_load", "executions", "execution", "errors_summary", "usage_summary"]
    scope_object_write_actions: list[str] = ["configure"]

    def _require_project_admin(self) -> None:
        membership_level = self.user_permissions.current_team.effective_membership_level
        if membership_level is None or membership_level < OrganizationMembership.Level.ADMIN:
            raise ValidationError("Project admin access is required to configure tenant queries.")

    @validated_request(
        TenantQueryRequestSerializer,
        responses={200: OpenApiResponse(response=TenantQueryResponseSerializer)},
        tags=[ProductKey.DATA_WAREHOUSE],
        summary="Run a tenant-scoped direct Postgres HogQL query",
        description=(
            "Executes a HogQL SELECT query against a direct Postgres connection with the configured tenant predicate "
            "enforced on every enabled table."
        ),
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        validated_data = cast(ValidatedRequest, request).validated_data
        request_user = request.user if isinstance(request.user, User) else None

        try:
            result, _row_count = execute_tenant_query(
                team=self.team,
                user=request_user,
                connection_id=str(validated_data["connection_id"]),
                tenant_value=validated_data.get("tenant_value"),
                query=validated_data["query"],
                timeout_ms=validated_data.get("timeout_ms"),
            )
        except ExposedHogQLError as error:
            raise ValidationError(str(error)) from error

        return Response(result)

    @validated_request(
        TenantQueryConfigLoadRequestSerializer,
        responses={200: OpenApiResponse(response=TenantQueryConfigResponseSerializer)},
        tags=[ProductKey.DATA_WAREHOUSE],
        summary="Load tenant query configuration",
        description="Returns the tenant query configuration for a direct Postgres connection.",
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="config/load",
        required_scopes=["external_data_source:read"],
    )
    def config_load(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        validated_data = cast(ValidatedRequest, request).validated_data

        try:
            result = get_tenant_query_config(
                team=self.team,
                connection_id=str(validated_data["connection_id"]),
            )
        except ExposedHogQLError as error:
            raise ValidationError(str(error)) from error

        return Response(result)

    @validated_request(
        TenantQueryExecutionsRequestSerializer,
        responses={200: OpenApiResponse(response=TenantQueryExecutionsResponseSerializer)},
        tags=[ProductKey.DATA_WAREHOUSE],
        summary="List tenant query executions",
        description="Returns recent tenant query execution logs for auditing and debugging tenant query service usage.",
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="executions",
        required_scopes=["query:read", "logs:read"],
    )
    def executions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        validated_data = cast(ValidatedRequest, request).validated_data

        try:
            result = list_tenant_query_executions(
                team=self.team,
                connection_id=str(validated_data["connection_id"]) if validated_data.get("connection_id") else None,
                tenant_value=validated_data.get("tenant_value"),
                date_from=validated_data.get("date_from"),
                date_to=validated_data.get("date_to"),
                success=validated_data.get("success"),
                limit=validated_data.get("limit"),
            )
        except ExposedHogQLError as error:
            raise ValidationError(str(error)) from error

        return Response(result)

    @validated_request(
        TenantQueryExecutionDetailRequestSerializer,
        responses={200: OpenApiResponse(response=TenantQueryExecutionDetailResponseSerializer)},
        tags=[ProductKey.DATA_WAREHOUSE],
        summary="Get tenant query execution detail",
        description="Returns a single tenant query execution log with captured table and connection metadata.",
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="execution",
        required_scopes=["query:read", "logs:read"],
    )
    def execution(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        validated_data = cast(ValidatedRequest, request).validated_data

        try:
            execution = get_tenant_query_execution(
                team=self.team,
                execution_id=validated_data["execution_id"],
                timestamp=validated_data.get("timestamp"),
            )
        except ExposedHogQLError as error:
            raise ValidationError(str(error)) from error

        if execution is None:
            raise NotFound("Tenant query execution not found.")

        return Response({"execution": execution})

    @validated_request(
        TenantQueryObservabilityRequestSerializer,
        responses={200: OpenApiResponse(response=TenantQueryErrorSummaryResponseSerializer)},
        tags=[ProductKey.DATA_WAREHOUSE],
        summary="Summarize tenant query errors",
        description="Groups failed tenant query executions by tenant, referenced tables, original query, and error.",
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="errors/summary",
        required_scopes=["query:read", "logs:read"],
    )
    def errors_summary(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        validated_data = cast(ValidatedRequest, request).validated_data

        try:
            result = summarize_tenant_query_errors(
                team=self.team,
                connection_id=str(validated_data["connection_id"]) if validated_data.get("connection_id") else None,
                tenant_value=validated_data.get("tenant_value"),
                date_from=validated_data.get("date_from"),
                date_to=validated_data.get("date_to"),
                limit=validated_data.get("limit"),
            )
        except ExposedHogQLError as error:
            raise ValidationError(str(error)) from error

        return Response(result)

    @validated_request(
        TenantQueryObservabilityRequestSerializer,
        responses={200: OpenApiResponse(response=TenantQueryUsageSummaryResponseSerializer)},
        tags=[ProductKey.DATA_WAREHOUSE],
        summary="Summarize tenant query usage",
        description="Groups tenant query executions by tenant and referenced tables for usage and auditing.",
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="usage/summary",
        required_scopes=["query:read", "logs:read"],
    )
    def usage_summary(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        validated_data = cast(ValidatedRequest, request).validated_data

        try:
            result = summarize_tenant_query_usage(
                team=self.team,
                connection_id=str(validated_data["connection_id"]) if validated_data.get("connection_id") else None,
                tenant_value=validated_data.get("tenant_value"),
                date_from=validated_data.get("date_from"),
                date_to=validated_data.get("date_to"),
                limit=validated_data.get("limit"),
            )
        except ExposedHogQLError as error:
            raise ValidationError(str(error)) from error

        return Response(result)

    @validated_request(
        TenantQueryConfigRequestSerializer,
        responses={200: OpenApiResponse(response=TenantQueryConfigResponseSerializer)},
        tags=[ProductKey.DATA_WAREHOUSE],
        summary="Configure tenant query service",
        description=(
            "Enables or updates tenant-scoped querying for a direct Postgres connection. Tables missing the configured "
            "tenant column are disabled and returned as a warning payload."
        ),
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="config",
        required_scopes=["external_data_source:write"],
    )
    def configure(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._require_project_admin()
        validated_data = cast(ValidatedRequest, request).validated_data

        try:
            result = configure_tenant_query(
                team=self.team,
                connection_id=str(validated_data["connection_id"]),
                enabled=validated_data["enabled"],
                tenant_column_name=validated_data.get("tenant_column_name"),
                tenant_column_names_by_table=validated_data.get("tenant_column_names_by_table"),
                default_timeout_ms=validated_data.get("default_timeout_ms"),
                max_timeout_ms=validated_data.get("max_timeout_ms"),
                max_result_limit=validated_data.get("max_result_limit"),
            )
        except ExposedHogQLError as error:
            raise ValidationError(str(error)) from error

        return Response(result)
