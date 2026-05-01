from __future__ import annotations

import datetime as dt

import structlog
import temporalio
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
from posthog.temporal.ducklake.promote_table_schedule import (
    delete_promote_table_schedule,
    sync_promote_table_schedule,
    trigger_promote_table_schedule,
)

from products.data_warehouse.backend.models import ManagedWarehousePromotedTable

# Schemas that are part of the duckgres / DuckLake / Postgres infrastructure and
# should never appear as promotable tables. Filtered both in SQL (as a hint to
# duckgres) and again in Python (as the trustworthy filter).
_SYSTEM_SCHEMAS = frozenset(
    {"pg_catalog", "information_schema", "pg_toast", "__ducklake_metadata_ducklake"}
)

_AVAILABLE_TABLES_SQL = """
    SELECT table_schema, table_name, table_type
    FROM information_schema.tables
    WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast', '__ducklake_metadata_ducklake')
      AND table_type IN ('BASE TABLE', 'VIEW')
    ORDER BY table_schema, table_name
"""

logger = structlog.get_logger(__name__)


_ALLOWED_FREQUENCIES: dict[str, dt.timedelta] = {
    "5min": dt.timedelta(minutes=5),
    "15min": dt.timedelta(minutes=15),
    "30min": dt.timedelta(minutes=30),
    "1hour": dt.timedelta(hours=1),
    "6hour": dt.timedelta(hours=6),
    "12hour": dt.timedelta(hours=12),
    "24hour": dt.timedelta(hours=24),
}


def _interval_to_frequency(interval: dt.timedelta | None) -> str:
    if interval is None:
        return "1hour"
    for label, value in _ALLOWED_FREQUENCIES.items():
        if value == interval:
            return label
    return "1hour"


class ManagedWarehousePromotedTableSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    sync_frequency = serializers.ChoiceField(
        choices=list(_ALLOWED_FREQUENCIES.keys()),
        write_only=True,
        required=False,
        help_text="Refresh interval. One of: 5min, 15min, 30min, 1hour, 6hour, 12hour, 24hour.",
    )
    sync_frequency_interval = serializers.SerializerMethodField(
        read_only=True,
        help_text="Refresh interval, returned as a frequency label (e.g. '1hour').",
    )
    data_warehouse_table_id = serializers.UUIDField(
        source="data_warehouse_table.id",
        read_only=True,
        allow_null=True,
        help_text="ID of the DataWarehouseTable that exposes the promoted parquet snapshot.",
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
            "sync_frequency",
            "sync_frequency_interval",
            "status",
            "last_error",
            "last_run_started_at",
            "last_synced_at",
            "row_count",
            "size_in_s3_mib",
            "data_warehouse_table_id",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "updated_at",
            "status",
            "last_error",
            "last_run_started_at",
            "last_synced_at",
            "row_count",
            "size_in_s3_mib",
            "data_warehouse_table_id",
        ]
        extra_kwargs = {
            "source_schema_name": {
                "help_text": "Schema name of the source table in the customer's DuckLake catalog.",
            },
            "source_table_name": {
                "help_text": "Table name of the source table in the customer's DuckLake catalog.",
            },
            "status": {
                "help_text": "Status of the most recent run: pending, running, completed, or failed.",
            },
        }

    def get_sync_frequency_interval(self, obj: ManagedWarehousePromotedTable) -> str:
        return _interval_to_frequency(obj.sync_frequency_interval)

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
        frequency_label = validated_data.pop("sync_frequency", "1hour")
        interval = _ALLOWED_FREQUENCIES[frequency_label]

        team = self.context["get_team"]()
        request = self.context["request"]

        promoted = ManagedWarehousePromotedTable.objects.create(
            team=team,
            created_by=request.user if request.user.is_authenticated else None,
            sync_frequency_interval=interval,
            **validated_data,
        )

        try:
            sync_promote_table_schedule(promoted, create=True, trigger_immediately=True)
        except temporalio.service.RPCError:
            logger.exception("Failed to create Temporal schedule for promoted table")
            promoted.delete()
            raise

        return promoted

    def update(self, instance: ManagedWarehousePromotedTable, validated_data: dict) -> ManagedWarehousePromotedTable:
        frequency_label = validated_data.pop("sync_frequency", None)

        for field, value in validated_data.items():
            setattr(instance, field, value)

        if frequency_label is not None:
            instance.sync_frequency_interval = _ALLOWED_FREQUENCIES[frequency_label]

        instance.save()

        if frequency_label is not None:
            try:
                sync_promote_table_schedule(instance, create=False)
            except temporalio.service.RPCError:
                logger.exception("Failed to update Temporal schedule for promoted table")
                raise

        return instance


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
        try:
            delete_promote_table_schedule(instance.schedule_id)
        except temporalio.service.RPCError:
            logger.exception("Failed to delete Temporal schedule for promoted table")

    @extend_schema(
        request=None,
        responses={status.HTTP_202_ACCEPTED: ManagedWarehousePromotedTableSerializer},
        description="Trigger an immediate refresh of this promoted table outside of its schedule.",
    )
    @action(methods=["POST"], detail=True)
    def trigger(self, request: Request, *args, **kwargs) -> Response:
        promoted = self.get_object()
        try:
            trigger_promote_table_schedule(promoted.schedule_id)
        except temporalio.service.RPCError as exc:
            logger.exception("Failed to trigger Temporal schedule for promoted table")
            raise ValidationError(f"Could not trigger refresh: {exc}") from exc
        serializer = self.get_serializer(promoted)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

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
            result = execute_ducklake_query(
                team_id,
                sql=_AVAILABLE_TABLES_SQL,
            )
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
