from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.data_warehouse.backend.tenant_query import configure_tenant_query, execute_tenant_query


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
    default_timeout_ms = serializers.IntegerField(help_text="Default statement timeout in milliseconds.")
    max_timeout_ms = serializers.IntegerField(help_text="Maximum allowed statement timeout in milliseconds.")
    max_result_limit = serializers.IntegerField(help_text="Maximum result row limit.")
    enabled_tables = serializers.ListField(
        child=serializers.CharField(),
        help_text="Enabled direct Postgres tables included in tenant query validation.",
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


class TenantQueryViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    serializer_class = TenantQueryRequestSerializer
    scope_object = "query"
    scope_object_read_actions = ["create"]
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
        TenantQueryConfigRequestSerializer,
        responses={200: OpenApiResponse(response=TenantQueryConfigResponseSerializer)},
        tags=[ProductKey.DATA_WAREHOUSE],
        summary="Configure tenant query service",
        description=(
            "Enables or updates tenant-scoped querying for a direct Postgres connection after validating that every "
            "enabled table has the configured tenant column."
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
                default_timeout_ms=validated_data.get("default_timeout_ms"),
                max_timeout_ms=validated_data.get("max_timeout_ms"),
                max_result_limit=validated_data.get("max_result_limit"),
            )
        except ExposedHogQLError as error:
            raise ValidationError(str(error)) from error

        return Response(result)
