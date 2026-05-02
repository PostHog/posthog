from __future__ import annotations

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.ducklake.client import execute_ducklake_query
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.data_warehouse.backend.models import DataWarehouseTable, ManagedWarehousePromotedTable
from products.data_warehouse.backend.models.util import postgres_column_to_dwh_column

logger = structlog.get_logger(__name__)

# Schemas that are part of the duckgres / DuckLake / Postgres infrastructure and
# should never appear as promotable tables. Filtered both in SQL (as a hint to
# duckgres) and again in Python (as the trustworthy filter).
_SYSTEM_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast", "__ducklake_metadata_ducklake"})

_AVAILABLE_TABLES_SQL = """
    SELECT table_schema, table_name, table_type
    FROM information_schema.tables
    WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast', '__ducklake_metadata_ducklake')
      AND table_type IN ('BASE TABLE', 'VIEW')
    ORDER BY table_schema, table_name
"""


def _escape_sql_string(value: str) -> str:
    """Escape a string literal for inline embedding in raw SQL.

    The ducklake client wrapper doesn't expose parameter binding for raw SQL,
    so we escape single quotes ourselves. Used for schema/table identifiers
    that have already been validated as non-empty strings.
    """
    return value.replace("'", "''")


def _columns_introspection_sql(schema: str, table: str) -> str:
    return f"""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = '{_escape_sql_string(schema)}' AND table_name = '{_escape_sql_string(table)}'
        ORDER BY ordinal_position
    """


class ManagedWarehousePromotedTableSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    data_warehouse_table_id = serializers.UUIDField(
        source="data_warehouse_table.id",
        read_only=True,
        allow_null=True,
        help_text="ID of the DataWarehouseTable that exposes the promoted table to HogQL queries.",
    )
    data_warehouse_table_name = serializers.CharField(
        source="data_warehouse_table.name",
        read_only=True,
        allow_null=True,
        help_text="Display name of the linked DataWarehouseTable.",
    )

    class Meta:
        model = ManagedWarehousePromotedTable
        fields = [
            "id",
            "created_at",
            "created_by",
            "updated_at",
            "source_schema_name",
            "source_table_name",
            "data_warehouse_table_id",
            "data_warehouse_table_name",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "updated_at",
            "data_warehouse_table_id",
            "data_warehouse_table_name",
        ]
        extra_kwargs = {
            "source_schema_name": {
                "help_text": "Schema name of the source table in the customer's DuckLake catalog.",
            },
            "source_table_name": {
                "help_text": "Table name of the source table in the customer's DuckLake catalog.",
            },
        }

    def validate_source_schema_name(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValidationError("source_schema_name is required")
        return cleaned

    def validate_source_table_name(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValidationError("source_table_name is required")
        return cleaned

    def create(self, validated_data: dict) -> ManagedWarehousePromotedTable:
        team = self.context["get_team"]()
        request = self.context["request"]

        schema_name = validated_data["source_schema_name"]
        table_name = validated_data["source_table_name"]

        columns = _introspect_columns(team.id, schema_name, table_name)

        promoted = ManagedWarehousePromotedTable.objects.create(
            team=team,
            created_by=request.user if request.user.is_authenticated else None,
            **validated_data,
        )

        DataWarehouseTable.objects.create(
            team=team,
            name=f"{schema_name}.{table_name}",
            format=DataWarehouseTable.TableFormat.ManagedWarehouse,
            url_pattern="",
            columns=columns,
            managed_warehouse_promoted_table=promoted,
        )

        return promoted


class AvailableSourceTableSerializer(serializers.Serializer):
    """A table in the customer's DuckLake catalog that could be promoted."""

    schema = serializers.CharField(help_text="Schema name in the customer's DuckLake catalog.")
    name = serializers.CharField(help_text="Table or view name in the customer's DuckLake catalog.")
    table_type = serializers.ChoiceField(
        choices=["BASE TABLE", "VIEW"],
        help_text="Whether this is a base table or a view.",
    )
    already_promoted = serializers.BooleanField(
        help_text="True if this schema/name pair already has an active promotion for this team.",
    )


def _introspect_columns(team_id: int, schema: str, table: str) -> dict[str, dict]:
    """Run information_schema.columns against duckgres and map types to ClickHouse/HogQL."""
    try:
        result = execute_ducklake_query(team_id, sql=_columns_introspection_sql(schema, table))
    except Exception as exc:
        logger.exception("Failed to introspect managed warehouse columns")
        raise ValidationError(f"Could not introspect '{schema}.{table}': {exc}") from exc

    if not result.results:
        raise ValidationError(f"Table '{schema}.{table}' was not found in the managed warehouse")

    columns: dict[str, dict] = {}
    for row in result.results:
        column_name, postgres_type, is_nullable_raw = row[0], row[1], row[2]
        nullable = str(is_nullable_raw).upper() == "YES"
        columns[column_name] = postgres_column_to_dwh_column(column_name, postgres_type, nullable)
    return columns


class ManagedWarehousePromotedTableViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """Manage tables promoted from a customer's managed DuckLake warehouse to PostHog."""

    scope_object = "INTERNAL"
    queryset = ManagedWarehousePromotedTable.objects.none()
    serializer_class = ManagedWarehousePromotedTableSerializer

    def safely_get_queryset(self, queryset):
        return ManagedWarehousePromotedTable.objects.filter(team_id=self.team_id, deleted=False).select_related(
            "created_by", "data_warehouse_table"
        )

    def perform_destroy(self, instance: ManagedWarehousePromotedTable) -> None:
        instance.deleted = True
        instance.save(update_fields=["deleted", "updated_at"])
        # The linked DataWarehouseTable is owned by this promotion — soft-delete it too so
        # HogQL queries stop resolving it.
        try:
            table = instance.data_warehouse_table
        except DataWarehouseTable.DoesNotExist:
            table = None
        if table is not None:
            table.deleted = True
            table.save(update_fields=["deleted", "updated_at"])

    @extend_schema(
        request=None,
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=AvailableSourceTableSerializer(many=True),
                description="Tables and views available to promote from the customer's DuckLake catalog.",
            ),
        },
        description=(
            "List tables and views in the customer's managed DuckLake catalog that are eligible to "
            "promote, with a flag indicating whether each one is already promoted for this team."
        ),
    )
    @action(methods=["GET"], detail=False, url_path="available_source_tables")
    def available_source_tables(self, request: Request, *args, **kwargs) -> Response:
        team_id = self.team_id

        already_promoted: set[tuple[str, str]] = set(
            ManagedWarehousePromotedTable.objects.filter(team_id=team_id, deleted=False).values_list(
                "source_schema_name", "source_table_name"
            )
        )

        try:
            result = execute_ducklake_query(team_id, sql=_AVAILABLE_TABLES_SQL)
        except Exception as exc:
            logger.exception("Failed to list available source tables from duckgres")
            raise ValidationError(f"Could not query the managed warehouse: {exc}") from exc

        rows = [
            {
                "schema": row[0],
                "name": row[1],
                "table_type": row[2],
                "already_promoted": (row[0], row[1]) in already_promoted,
            }
            for row in result.results
            if row[0] not in _SYSTEM_SCHEMAS
        ]

        serializer = AvailableSourceTableSerializer(rows, many=True)
        return Response(serializer.data)
