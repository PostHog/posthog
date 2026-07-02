import datetime as dt
from collections.abc import Callable
from typing import Any, Optional, cast

from django.db import transaction

import structlog
import temporalio
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import filters, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql.database.database import Database

from posthog.api.log_entries import LogEntryRequestSerializer, LogEntrySerializer, fetch_log_entries
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User
from posthog.utils import str_to_bool

from products.data_warehouse.backend.facade.api import (
    cancel_external_data_workflow,
    create_and_register_webhook,
    external_data_workflow_exists,
    get_or_create_webhook_hog_function,
    get_postgres_source_location,
    hide_direct_mysql_table,
    hide_direct_postgres_table,
    hide_direct_snowflake_table,
    is_any_external_data_schema_paused,
    is_cdc_enabled_for_team,
    is_xmin_enabled_for_team,
    pause_external_data_schedule,
    reconcile_webhook_events,
    reproject_direct_mysql_table,
    reproject_direct_postgres_table,
    reproject_direct_snowflake_table,
    sync_cdc_extraction_schedule,
    sync_external_data_job_workflow,
    trigger_external_data_workflow,
    unpause_external_data_schedule,
)
from products.warehouse_sources.backend.facade.models import (
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.facade.source_management import (
    RowFilterValidationError,
    SourceRegistry,
    WebhookSource,
    filter_dwh_columns_by_enabled_columns as _filter_dwh_columns_by_enabled_columns,
    get_cdc_adapter,
    source_type_supports_cdc,
    validate_and_coerce_row_filters,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType, IncrementalFieldType

logger = structlog.get_logger(__name__)


def source_supports_column_selection(source_type: str) -> bool:
    """Column selection is available for every registered source: SQL sources project the
    selection into their SELECT, everything else is projected generically just before the
    Delta write. Unknown source types stay False so the UI fails closed.

    Excludes managed-schema sources (Stripe, Paddle, Zendesk): their HogQL tables expose a
    fixed canonical schema, so dropping a referenced column breaks the query."""
    try:
        source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
    except Exception as e:
        capture_exception(e)
        return False
    return not source.has_managed_hogql_schema


def source_supports_row_filters(source_type: str) -> bool:
    try:
        source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
    except Exception as e:
        capture_exception(e)
        return False
    # `bool()` guards against test mocks whose attribute access returns a Mock — orjson can't serialize.
    return bool(source.supports_row_filters)


_CDC_WRITE_TARGETS_BY_TABLE_MODE: dict[str, frozenset[str]] = {
    "consolidated": frozenset({"consolidated"}),
    "cdc_only": frozenset({"cdc_history"}),
    "both": frozenset({"consolidated", "cdc_history"}),
}


def _cdc_table_mode_change_needs_resnapshot(old_mode: str | None, new_mode: str | None) -> bool:
    """True when the new mode adds a physical write target (consolidated and/or cdc history table)."""
    if old_mode == new_mode:
        return False
    old_targets = _CDC_WRITE_TARGETS_BY_TABLE_MODE.get(old_mode or "", frozenset())
    new_targets = _CDC_WRITE_TARGETS_BY_TABLE_MODE.get(new_mode or "", frozenset())
    return bool(new_targets - old_targets)


def _reset_cdc_for_full_resnapshot(instance: ExternalDataSchema) -> None:
    """Cancel any running workflow and reset schema state so the next run does a full snapshot.

    Must save before triggering: the workflow reloads the schema and bails via
    `CDCHandledExternally` if it sees `cdc_mode='streaming'`.
    """
    latest_running_job = (
        ExternalDataJob.objects.filter(schema_id=instance.pk, team_id=instance.team_id).order_by("-created_at").first()
    )
    if latest_running_job and latest_running_job.workflow_id and latest_running_job.status == "Running":
        try:
            cancel_external_data_workflow(latest_running_job.workflow_id)
        except temporalio.service.RPCError as e:
            logger.exception(
                "Could not cancel running workflow before re-snapshot",
                schema_id=str(instance.id),
                exc_info=e,
            )

    # Merge under a row lock so the reset can't clobber a concurrent CDC extract activity's
    # sync_type_config writes (and the status/initial_sync_complete save below skips the JSON
    # column, leaving no second window for the merged config to be overwritten).
    instance.sync_type_config = update_sync_type_config_keys(
        instance.id,
        instance.team_id,
        updates={"reset_pipeline": True, "cdc_mode": "snapshot"},
        removes=["cdc_last_log_position", "cdc_deferred_runs"],
    )
    instance.initial_sync_complete = False
    instance.status = ExternalDataSchema.Status.RUNNING
    instance.save(update_fields=["initial_sync_complete", "status", "updated_at"])

    try:
        trigger_external_data_workflow(instance)
    except temporalio.service.RPCError as e:
        logger.exception(
            "Could not trigger external data workflow after re-snapshot reset",
            schema_id=str(instance.id),
            exc_info=e,
        )
        # Roll the status back so the Syncs UI doesn't show RUNNING for a workflow that never started.
        # The sync_type_config mutations stay — the schema's intent is still "do a re-snapshot next run".
        instance.status = ExternalDataSchema.Status.FAILED
        instance.save(update_fields=["status"])


# Sync frequencies that only CDC schemas may use. Every other sync type floors at 5 minutes.
CDC_ONLY_SYNC_FREQUENCIES = {"1min"}
NON_CDC_FLOOR_SYNC_FREQUENCY = "5min"


@extend_schema_field(
    {
        "type": "array",
        "nullable": True,
        "items": {
            "type": "object",
            "properties": {
                "column": {"type": "string"},
                # Not an OpenAPI `enum`: the operators are punctuation with no nameable identifier,
                # so orval collapses the enum to duplicate empty-string keys (`'': '>'`, …) in the
                # generated clients. Keep it a plain string and list the allowed values in the
                # description; validation is enforced server-side regardless.
                "operator": {
                    "type": "string",
                    "description": 'One of: > >= < <= = != IN "NOT IN".',
                },
                "value": {
                    "description": (
                        "Comparison value; must match the column's type. For `IN` / `NOT IN`, a "
                        "comma-separated list (e.g. `1, 2, 3` or `'a','b'`)."
                    )
                },
            },
            "required": ["column", "operator", "value"],
        },
    }
)
class RowFiltersField(serializers.JSONField):
    """Typed JSON field for the list of `{column, operator, value}` row-filter predicates."""


def unsupported_row_filter_reason(*, is_direct_query: bool, is_cdc: bool) -> str | None:
    """Row filters are only enforced on snapshot-style syncs, which apply them as a `WHERE`
    clause. Direct-query sources read tables live and CDC streams WAL changes — both bypass that
    query, so a saved filter would silently leave excluded rows visible. Reject those up front.

    This covers every direct engine (Postgres, MySQL, Snowflake): none of the live-query executors
    apply the predicates, so accepting a filter would be a silent data-restriction bypass.
    """
    if is_direct_query:
        return (
            "Row filters are not supported for direct-query sources — "
            "tables are queried live and filters cannot be enforced at the source."
        )
    if is_cdc:
        return (
            "Row filters are not supported for CDC schemas — change-stream rows are "
            "replicated without these predicates, so filtered rows would still sync."
        )
    return None


def _apply_primary_key_columns(
    data: dict[str, Any],
    payload: dict[str, Any],
    instance: Any,
    label: str,
) -> None:
    """Apply primary_key_columns from request data to the sync_type_config payload.

    Raises ValidationError if the PK changed after data has been synced, or if no PK is set.
    """
    new_pk = data.get("primary_key_columns")
    if new_pk:
        old_pk = payload.get("primary_key_columns")
        if new_pk != old_pk and instance.table is not None:
            raise ValidationError(
                "Primary key cannot be changed after data has been synced. "
                "Delete the synced data first, then change the primary key."
            )
        payload["primary_key_columns"] = new_pk
    elif not payload.get("primary_key_columns"):
        raise ValidationError(
            f"{label} requires a primary key on table '{instance.name}'. "
            "Provide primary_key_columns or refresh schema discovery to pick one up."
        )


class ExternalDataSchemaSerializer(serializers.ModelSerializer):
    table = serializers.SerializerMethodField(read_only=True)
    incremental = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    sync_type = serializers.ChoiceField(
        choices=ExternalDataSchema.SyncType.choices,
        required=False,
        allow_null=True,
        help_text="Sync strategy: incremental, full_refresh, append, cdc, or xmin.",
    )
    incremental_field = serializers.CharField(
        required=False, allow_null=True, help_text="Column name used to track sync progress."
    )
    incremental_field_type = serializers.ChoiceField(
        choices=[(e.value, e.value) for e in IncrementalFieldType],
        required=False,
        allow_null=True,
        help_text="Data type of the incremental field.",
    )
    incremental_field_lookback_seconds = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=5_184_000,  # 60 days — larger windows defeat incremental efficiency
        help_text=(
            "Seconds to subtract from the stored incremental watermark at sync time, so each "
            "incremental run re-reads a rolling overlap window and catches late or backdated rows. "
            "Applies to timestamp/date incremental fields only. The stored watermark is unchanged. "
            "Maximum 5184000 (60 days)."
        ),
    )
    sync_frequency = serializers.ChoiceField(
        choices=[
            ("never", "never"),
            ("1min", "1min"),
            ("5min", "5min"),
            ("15min", "15min"),
            ("30min", "30min"),
            ("1hour", "1hour"),
            ("6hour", "6hour"),
            ("12hour", "12hour"),
            ("24hour", "24hour"),
            ("7day", "7day"),
            ("30day", "30day"),
        ],
        required=False,
        allow_null=True,
        help_text="How often to sync.",
    )
    sync_time_of_day = serializers.TimeField(
        required=False, allow_null=True, help_text="UTC time of day to run the sync (HH:MM:SS)."
    )
    primary_key_columns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text="Column names for primary key deduplication.",
    )
    cdc_table_mode = serializers.ChoiceField(
        choices=["consolidated", "cdc_only", "both"],
        required=False,
        allow_null=True,
        help_text="For CDC syncs: consolidated, cdc_only, or both.",
    )
    enabled_columns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text=(
            "Names of source columns to sync. `null` (default) syncs all columns. "
            "Primary-key columns and the active incremental field are always retained, "
            "even if not listed here."
        ),
    )
    row_filters = RowFiltersField(
        required=False,
        allow_null=True,
        help_text=(
            "Predicates ANDed onto the source query so only matching rows sync. Each is "
            "`{column, operator, value}`; `null`/empty (default) syncs all rows. The operator "
            'must be one of `> >= < <= = != IN "NOT IN"` and the value must match the column\'s '
            "type (for `IN`/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). "
            "Applied on the next sync — not retroactive to already-synced rows."
        ),
    )
    available_columns = serializers.SerializerMethodField(
        read_only=True,
        help_text="Column metadata (name, data type, nullable) for this schema. For SQL sources this is the "
        "source-side schema discovered via `refresh_schemas`; for other sources (and once synced) it falls back "
        "to the synced table's columns. Empty only before the first successful sync/refresh.",
    )
    # `source` shadows DRF's reserved `Field.source` attribute, so mypy flags the assignment;
    # the runtime behaviour (a read-only SerializerMethodField backed by get_source) is correct.
    source = serializers.SerializerMethodField(  # type: ignore[assignment]
        read_only=True,
        help_text="Lightweight parent-source summary (id, source_type, column-selection support, the requesting "
        "user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so "
        "read-only views can render without fetching the full source and all its schemas.",
    )

    class Meta:
        model = ExternalDataSchema

        fields = [
            "id",
            "name",
            "label",
            "table",
            "should_sync",
            "last_synced_at",
            "latest_error",
            "incremental",
            "status",
            "sync_type",
            "incremental_field",
            "incremental_field_type",
            "incremental_field_lookback_seconds",
            "sync_frequency",
            "sync_time_of_day",
            "description",
            "primary_key_columns",
            "cdc_table_mode",
            "enabled_columns",
            "row_filters",
            "available_columns",
            "source",
        ]

        read_only_fields = [
            "id",
            "name",
            "label",
            "table",
            "last_synced_at",
            "latest_error",
            "status",
            "description",
            "available_columns",
            "source",
        ]

    @extend_schema_field(
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "data_type": {"type": "string"},
                    "is_nullable": {"type": "boolean"},
                },
                "required": ["name"],
            },
        }
    )
    def get_available_columns(self, schema: ExternalDataSchema) -> list[dict[str, Any]]:
        metadata = schema.schema_metadata or {}
        columns = metadata.get("columns") if isinstance(metadata, dict) else None
        if isinstance(columns, list):
            sql_columns = [
                {
                    "name": column.get("name"),
                    "data_type": column.get("data_type"),
                    "is_nullable": column.get("is_nullable"),
                }
                for column in columns
                if isinstance(column, dict) and isinstance(column.get("name"), str)
            ]
            if sql_columns:
                return sql_columns
        # `schema_metadata` is only written on source creation and explicit schema reload
        # (`refresh_schemas`) — never by background schema discovery or the data sync, and never for
        # non-SQL sources. So it's empty for non-SQL sources and for SQL schemas discovered/added later
        # or not yet reloaded. Fall back to the synced table's universal column store so the Descriptions
        # UI can still list columns (and surface their existing annotations) and let users edit them.
        table = schema.table
        return table.get_user_facing_columns() if table is not None else []

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "id": {"type": "string"},
                "source_type": {"type": "string"},
                "supports_column_selection": {"type": "boolean"},
                "supports_row_filters": {"type": "boolean"},
                "user_access_level": {"type": "string", "nullable": True},
            },
        }
    )
    def get_source(self, schema: ExternalDataSchema) -> dict[str, Any] | None:
        # Gated to the retrieve action (via `include_source` context) so the source endpoint's
        # nested schema serialization and the schema `list` don't pay for the SourceRegistry lookup.
        if not self.context.get("include_source"):
            return None
        source = schema.source
        user_access_level = None
        view = self.context.get("view")
        user_access_control = getattr(view, "user_access_control", None)
        if user_access_control is not None:
            user_access_level = user_access_control.get_user_access_level(source)
        return {
            "id": str(source.id),
            "source_type": source.source_type,
            "supports_column_selection": source_supports_column_selection(source.source_type),
            "supports_row_filters": source_supports_row_filters(source.source_type),
            "user_access_level": user_access_level,
        }

    def get_status(self, schema: ExternalDataSchema) -> str | None:
        if schema.status == ExternalDataSchema.Status.BILLING_LIMIT_REACHED:
            return "Billing limits"

        if schema.status == ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW:
            return "Billing limits too low"

        return schema.status

    def get_incremental(self, schema: ExternalDataSchema) -> bool:
        return schema.is_incremental

    def get_table(self, schema: ExternalDataSchema) -> Optional[dict]:
        from products.data_warehouse.backend.presentation.views.table import SimpleTableSerializer

        if schema.table and schema.table.deleted:
            return None

        # Serializing table columns requires the full HogQL Database, which is expensive to build.
        # Callers that don't need columns (e.g. the source list) set include_columns=False so we skip it.
        include_columns = self.context.get("include_columns", True)
        table_context: dict[str, Any] = {"include_columns": include_columns, "team_id": self.context.get("team_id")}
        if include_columns:
            hogql_context = self.context.get("database", None)
            if not hogql_context:
                hogql_context = Database.create_for(
                    team_id=self.context["team_id"],
                    user=cast(User, self.context["request"].user),
                )
            table_context["database"] = hogql_context

        return SimpleTableSerializer(schema.table, context=table_context).data or None

    def to_representation(self, instance: ExternalDataSchema) -> dict:
        ret = super().to_representation(instance)
        ret["sync_type"] = ExternalDataSchema.SyncType(instance.sync_type) if instance.sync_type is not None else None
        ret["sync_frequency"] = sync_frequency_interval_to_sync_frequency(instance.sync_frequency_interval)
        ret["sync_time_of_day"] = (
            self.fields["sync_time_of_day"].to_representation(instance.sync_time_of_day)
            if instance.sync_time_of_day
            else None
        )
        ret["incremental_field"] = (
            instance.sync_type_config.get("incremental_field") if instance.sync_type_config else None
        )
        ret["incremental_field_type"] = (
            instance.sync_type_config.get("incremental_field_type") if instance.sync_type_config else None
        )
        ret["incremental_field_lookback_seconds"] = instance.incremental_field_lookback_seconds
        ret["primary_key_columns"] = instance.primary_key_columns
        ret["cdc_table_mode"] = instance.cdc_table_mode
        return ret

    def _run_temporal_side_effect(self, callback: Callable[[], None]) -> None:
        post_commit_actions = self.context.get("post_commit_actions")
        if isinstance(post_commit_actions, list):
            post_commit_actions.append(callback)
            return

        callback()

    def _save_merging_sync_type_config(
        self,
        instance: ExternalDataSchema,
        validated_data: dict[str, Any],
        original_sync_type_config: dict[str, Any],
    ) -> ExternalDataSchema:
        """Persist the update, replaying only the sync_type_config keys this request changed onto a
        freshly-locked copy of the row.

        super().update() does a full-instance save that rewrites sync_type_config wholesale from the
        copy loaded at the start of the request, so without this it would revert any key a concurrent
        CDC extract activity (cdc_last_log_position, cdc_deferred_runs, cdc_mode) committed in between.
        The lock is held across the save so nothing interleaves.
        """
        intended = instance.sync_type_config or {}
        changed = {
            key: value
            for key, value in intended.items()
            if key not in original_sync_type_config or original_sync_type_config[key] != value
        }
        removed = [key for key in original_sync_type_config if key not in intended]
        with transaction.atomic():
            locked = ExternalDataSchema.objects.select_for_update().get(pk=instance.pk)
            merged = locked.sync_type_config or {}
            merged.update(changed)
            for key in removed:
                merged.pop(key, None)
            instance.sync_type_config = merged
            validated_data["sync_type_config"] = merged
            return super().update(instance, validated_data)

    def update(self, instance: ExternalDataSchema, validated_data: dict[str, Any]) -> ExternalDataSchema:
        data = self.initial_data if isinstance(self.initial_data, dict) else {}

        # Capture the previous cdc_table_mode before any mutation so the post-save hook below can decide
        # whether the change adds a new physical write target (and therefore needs a re-snapshot).
        previous_cdc_table_mode = instance.cdc_table_mode

        # Snapshot sync_type_config before the branches below mutate it in place. The terminal save
        # diffs against this to persist only the keys this request changed. Shallow is enough: the
        # branches replace top-level keys (they never mutate a nested value in place), so a key is
        # "changed" iff its top-level value differs.
        original_sync_type_config = dict(instance.sync_type_config or {})

        # Refuse cdc_table_mode transitions that would kick a re-snapshot when the team is over its
        # monthly sync billing limit. Checked here (pre-save) so we don't end up with the new mode
        # persisted but no resnapshot triggered. Mirrors the gate in `resync` / `reload`.
        if (
            instance.sync_type == ExternalDataSchema.SyncType.CDC
            and "cdc_table_mode" in data
            and _cdc_table_mode_change_needs_resnapshot(previous_cdc_table_mode, data.get("cdc_table_mode"))
            and is_any_external_data_schema_paused(instance.team_id)
        ):
            raise ValidationError(
                "Monthly sync limit reached. Please increase your billing limit before changing "
                "the CDC table mode — a full re-snapshot would be required."
            )

        # Pop non-model fields from validated_data so super().update() doesn't try to set them
        validated_data.pop("sync_type", None)
        validated_data.pop("sync_frequency", None)
        validated_data.pop("sync_time_of_day", None)
        validated_data.pop("incremental_field", None)
        validated_data.pop("incremental_field_type", None)
        validated_data.pop("incremental_field_lookback_seconds", None)
        validated_data.pop("primary_key_columns", None)
        validated_data.pop("cdc_table_mode", None)

        if "enabled_columns" in validated_data:
            enabled_columns = validated_data["enabled_columns"]
            if enabled_columns is not None:
                # Managed-schema sources expose a fixed canonical HogQL schema; dropping a
                # referenced column breaks the query, so column selection isn't offered for them.
                if not source_supports_column_selection(instance.source.source_type):
                    raise ValidationError("Column selection is not supported for this source type.")
                if not isinstance(enabled_columns, list) or not all(isinstance(c, str) for c in enabled_columns):
                    raise ValidationError("enabled_columns must be a list of column-name strings or null.")
                metadata = instance.schema_metadata or {}
                metadata_columns = metadata.get("columns") if isinstance(metadata, dict) else None
                known = (
                    {col.get("name") for col in metadata_columns if isinstance(col, dict)}
                    if isinstance(metadata_columns, list)
                    else set()
                )
                if known:
                    unknown = [c for c in enabled_columns if c not in known]
                    if unknown:
                        raise ValidationError(
                            f"Unknown columns in enabled_columns: {sorted(unknown)}. "
                            "Run `Pull new schemas` to refresh available columns."
                        )

        # Validate against the schema's columns; raw filters are persisted as-is and re-coerced at sync time.
        if "row_filters" in validated_data and validated_data["row_filters"] is not None:
            # Only sources that push filters into their query (SQL WHERE) can honor them — a
            # saved-but-ignored filter would silently sync unfiltered rows.
            if not source_supports_row_filters(instance.source.source_type):
                raise ValidationError("Row filters are not supported for this source type.")
            incoming_sync_type = data.get("sync_type")
            target_is_cdc = (
                incoming_sync_type == ExternalDataSchema.SyncType.CDC if "sync_type" in data else instance.is_cdc
            )
            if reason := unsupported_row_filter_reason(
                is_direct_query=instance.source.is_direct_query, is_cdc=target_is_cdc
            ):
                raise ValidationError(reason)
            try:
                validate_and_coerce_row_filters(validated_data["row_filters"], instance.schema_metadata)
            except RowFilterValidationError as e:
                raise ValidationError(f"Invalid row filter: {e}")

        sync_type = data.get("sync_type")

        if sync_type == ExternalDataSchema.SyncType.CDC:
            from posthog.models import Team

            team = Team.objects.get(id=self.context["team_id"])
            if not is_cdc_enabled_for_team(team):
                raise ValidationError("CDC is not enabled for this team")

        # Close the enum-exposure window: `XMIN` is a valid `SyncType` choice, so the field accepts
        # "xmin" the moment the foundation lands. Reject it unless the source is Postgres, the flag is
        # on for the team, and the table actually advertises xmin support — otherwise a raw PATCH would
        # persist an xmin schema that silently degrades to full_refresh.
        if sync_type == ExternalDataSchema.SyncType.XMIN:
            from posthog.models import Team

            if instance.source.source_type != ExternalDataSourceType.POSTGRES:
                raise ValidationError("xmin replication is only available for Postgres sources.")
            team = Team.objects.get(id=self.context["team_id"])
            if not is_xmin_enabled_for_team(team):
                raise ValidationError("xmin replication is not enabled for this team")
            if not self._xmin_available_for_schema(instance):
                raise ValidationError(
                    f"xmin replication is not available for table '{instance.name}'. "
                    "It requires a Postgres heap table or materialized view on PostgreSQL 13+."
                )

        # Reject non-webhook sync types for webhook-only schemas (e.g. Stripe Discount —
        # no API list endpoint, so anything other than webhook produces an empty sync).
        if self._webhook_only_check_applies():
            if self._is_webhook_only_schema_cached(instance):
                raise ValidationError(
                    f"{instance.name} can only be synced via webhooks — pick the Webhook sync method."
                )

        # Only update sync_type if it was explicitly provided in the request
        if "sync_type" in data:
            validated_data["sync_type"] = sync_type

        # The sync type the schema will end up with: the new one if the request changes it, else the
        # existing one. Incremental-style config (incremental_field, incremental_field_type,
        # primary_key_columns, lookback) is keyed off this so a PATCH that edits only those fields —
        # without re-sending sync_type — still persists. Previously the whole block below was gated on
        # `sync_type` being in the request, so a bare `{"incremental_field": ...}` PATCH was silently
        # dropped while the 200 response still echoed the submitted value from the in-memory config.
        resulting_sync_type = sync_type if "sync_type" in data else instance.sync_type
        incremental_style_types = (
            ExternalDataSchema.SyncType.INCREMENTAL,
            ExternalDataSchema.SyncType.APPEND,
            ExternalDataSchema.SyncType.WEBHOOK,
        )

        # A bare edit (no sync_type in the request) of sync-config fields on a schema whose sync type
        # can't apply them would otherwise be an unpersisted no-op that still returns 200 — only the
        # incremental-style branch below writes these, and a non-incremental schema falls through it.
        # Reject it so the caller gets a clear error instead of a response that looks applied but isn't.
        # (primary_key_columns is included: CDC/xmin do use it, but only when sync_type is sent, so a
        # bare PK edit on those is dropped just like on full_refresh.)
        if "sync_type" not in data and resulting_sync_type not in incremental_style_types:
            unappliable_fields = [
                field
                for field in (
                    "incremental_field",
                    "incremental_field_type",
                    "incremental_field_lookback_seconds",
                    "primary_key_columns",
                )
                if field in data and data.get(field) is not None
            ]
            if unappliable_fields:
                raise ValidationError(
                    f"{', '.join(unappliable_fields)} cannot be applied to a schema with sync type "
                    f"{resulting_sync_type or 'not set'} on its own. "
                    "Include sync_type in the same request to change the sync type."
                )

        trigger_refresh = False
        # Update the validated_data with incremental fields
        if resulting_sync_type in incremental_style_types:
            payload = instance.sync_type_config

            if "primary_key_columns" in data:
                new_pk = data.get("primary_key_columns")
                old_pk = instance.sync_type_config.get("primary_key_columns")
                if (
                    resulting_sync_type == ExternalDataSchema.SyncType.INCREMENTAL
                    and new_pk != old_pk
                    and instance.table is not None
                ):
                    raise ValidationError(
                        "Primary key cannot be changed after data has been synced. "
                        "Delete the synced data first, then change the primary key."
                    )
                payload["primary_key_columns"] = new_pk

            # Detect incremental field changes before mutating payload
            incremental_field_changed = False
            incremental_field = data.get("incremental_field")
            if resulting_sync_type in (ExternalDataSchema.SyncType.INCREMENTAL, ExternalDataSchema.SyncType.APPEND):
                if "incremental_field" in data:
                    incremental_field_changed = (
                        payload.get("incremental_field") != incremental_field
                        or payload.get("incremental_field_last_value") is None
                    )

            if "incremental_field" in data:
                payload["incremental_field"] = incremental_field
            if "incremental_field_type" in data:
                payload["incremental_field_type"] = data.get("incremental_field_type")

            # Lookback only applies to incremental — merge-by-PK makes re-reading the overlap window
            # idempotent. `null` clears it.
            if (
                resulting_sync_type == ExternalDataSchema.SyncType.INCREMENTAL
                and "incremental_field_lookback_seconds" in data
            ):
                payload["incremental_field_lookback_seconds"] = data.get("incremental_field_lookback_seconds")

            if incremental_field_changed:
                if instance.table is not None and isinstance(incremental_field, str):
                    # Get the max_value and set it on incremental_field_last_value
                    max_value = instance.table.get_max_value_for_column(incremental_field)
                    if max_value:
                        instance.update_incremental_field_value(max_value, save=False)
                    else:
                        # if we can't get the max value, reset the table
                        payload["incremental_field_last_value"] = None
                        trigger_refresh = True

            validated_data["sync_type_config"] = payload
        elif sync_type == ExternalDataSchema.SyncType.CDC:
            payload = instance.sync_type_config
            if payload.get("cdc_mode") is None:
                payload["cdc_mode"] = "snapshot"
            cdc_table_mode = data.get("cdc_table_mode")
            if cdc_table_mode in ("consolidated", "cdc_only", "both"):
                payload["cdc_table_mode"] = cdc_table_mode

            # CDC needs a PK for UPDATE/DELETE merges. Accept the caller's PK or reuse what
            # discovery already stored; refuse the switch when neither is set.
            _apply_primary_key_columns(data, payload, instance, "CDC")

            validated_data["sync_type_config"] = payload
        elif sync_type == ExternalDataSchema.SyncType.XMIN:
            payload = instance.sync_type_config

            # xmin requires a primary key for clean upsert dedup, mirroring CDC. Accept the caller's
            # PK or reuse what discovery already stored; refuse the switch when neither is set.
            _apply_primary_key_columns(data, payload, instance, "xmin replication")

            validated_data["sync_type_config"] = payload
        else:
            # For CDC schemas where sync_type isn't being changed, still allow cdc_table_mode updates
            if instance.sync_type == ExternalDataSchema.SyncType.CDC and "cdc_table_mode" in data:
                cdc_table_mode = data.get("cdc_table_mode")
                if cdc_table_mode in ("consolidated", "cdc_only", "both"):
                    payload = instance.sync_type_config
                    payload["cdc_table_mode"] = cdc_table_mode
                    validated_data["sync_type_config"] = payload

        should_sync = validated_data.get("should_sync", None)
        sync_frequency = data.get("sync_frequency", None)
        sync_time_of_day_in_payload = "sync_time_of_day" in data
        sync_time_of_day = data.get("sync_time_of_day", None)
        was_sync_frequency_updated = False
        was_sync_time_of_day_updated = False
        source = instance.source

        # Sub-5-minute cadence is only valid for CDC. Enforce server-side so API/MCP callers (not
        # just the UI) can't drop a non-CDC schema below the allowed floor. We validate the
        # frequency the schema will actually end up with — the new value if one is supplied, else
        # the existing interval — against the sync type it will end up with. This also catches
        # switching a 1-minute CDC schema to a non-CDC type without re-sending the frequency.
        resulting_sync_type = sync_type if "sync_type" in data else instance.sync_type
        resulting_frequency = sync_frequency
        if not resulting_frequency and instance.sync_frequency_interval is not None:
            resulting_frequency = sync_frequency_interval_to_sync_frequency(instance.sync_frequency_interval)
        if resulting_frequency in CDC_ONLY_SYNC_FREQUENCIES and resulting_sync_type != ExternalDataSchema.SyncType.CDC:
            if sync_frequency:
                # The caller explicitly asked for a CDC-only cadence on a non-CDC schema — a direct
                # contradiction, so reject it.
                raise ValidationError(
                    "A 1-minute sync frequency is only available for CDC schemas. "
                    "The fastest frequency for other sync types is 5 minutes."
                )
            # Switching a CDC schema to a non-CDC type while it still carries a CDC-only cadence:
            # clamp to the non-CDC floor instead of dead-ending the switch. The clamp flows through
            # the sync_frequency handling below.
            sync_frequency = NON_CDC_FLOOR_SYNC_FREQUENCY

        if sync_frequency:
            sync_frequency_interval = sync_frequency_to_sync_frequency_interval(sync_frequency)

            if sync_frequency_interval != instance.sync_frequency_interval:
                was_sync_frequency_updated = True
                validated_data["sync_frequency_interval"] = sync_frequency_interval
                instance.sync_frequency_interval = sync_frequency_interval

        if sync_time_of_day is not None:
            try:
                new_time = dt.datetime.strptime(str(sync_time_of_day), "%H:%M:%S").time()
            except ValueError:
                raise ValidationError("Invalid sync time of day")

            if new_time != instance.sync_time_of_day:
                was_sync_time_of_day_updated = True
                validated_data["sync_time_of_day"] = sync_time_of_day
                instance.sync_time_of_day = sync_time_of_day
        else:
            if sync_time_of_day_in_payload and sync_time_of_day != instance.sync_time_of_day:
                was_sync_time_of_day_updated = True
                validated_data["sync_time_of_day"] = None
                instance.sync_time_of_day = None

        if source.supports_scheduled_sync and should_sync is True and sync_type is None and instance.sync_type is None:
            raise ValidationError("Sync type must be set up first before enabling schema")

        # Catches a CDC schema being flipped on later when sync_type isn't changing — the
        # sync_type branch above doesn't run, so PK presence isn't enforced there.
        effective_sync_type = sync_type or instance.sync_type
        if (
            should_sync is True
            and not instance.should_sync
            and effective_sync_type == ExternalDataSchema.SyncType.CDC
            and not instance.primary_key_columns
        ):
            raise ValidationError(
                f"CDC requires a primary key on table '{instance.name}'. "
                "Add a primary key on the source table and retry."
            )

        # Switching sync type across the xmin boundary changes the physical Delta schema: xmin
        # force-projects a non-nullable `_ph_xmin` control column that no other sync type writes.
        # Reusing the existing Delta table fails the write — the column is missing on the way in, or
        # lingers on the way out — so force a full resync to rebuild the table from scratch.
        if (
            "sync_type" in data
            and sync_type != instance.sync_type
            and ExternalDataSchema.SyncType.XMIN in (sync_type, instance.sync_type)
        ):
            if is_any_external_data_schema_paused(instance.team_id):
                raise ValidationError(
                    "Monthly sync limit reached. Please increase your billing limit before changing "
                    "the sync type — a full re-sync would be required."
                )
            validated_data.setdefault("sync_type_config", instance.sync_type_config)
            validated_data["sync_type_config"]["reset_pipeline"] = True
            if should_sync if should_sync is not None else instance.should_sync:
                trigger_refresh = True

        # When re-enabling a webhook schema, force a full refresh to avoid missing data
        if (
            should_sync is True
            and instance.should_sync is False
            and instance.is_webhook
            and instance.initial_sync_complete
        ):
            validated_data.setdefault("sync_type_config", instance.sync_type_config)
            validated_data["sync_type_config"]["reset_pipeline"] = True
            trigger_refresh = True

        enabled_columns_changed = "enabled_columns" in validated_data and (
            validated_data["enabled_columns"] != instance.enabled_columns
        )

        if source.is_direct_query:
            # Direct-mode lifecycle hooks that need a fresh DataWarehouseTable projection:
            # (1) row is being re-exposed (should_sync flipping False → True);
            # (2) the column-picker selection changed on an already-exposed row.
            newly_exposed = should_sync is True and instance.should_sync is False
            projection_needs_refresh = enabled_columns_changed and instance.table is not None and instance.should_sync
            if newly_exposed or projection_needs_refresh:
                if source.is_direct_postgres:
                    reproject = reproject_direct_postgres_table
                elif source.is_direct_snowflake:
                    reproject = reproject_direct_snowflake_table
                else:
                    reproject = reproject_direct_mysql_table
                validated_data["table"] = reproject(
                    instance,
                    source=source,
                    enabled_columns=validated_data.get("enabled_columns", instance.enabled_columns),
                )

            if should_sync is False and instance.should_sync is True:
                if source.is_direct_postgres:
                    hide_direct_postgres_table(instance.table)
                elif source.is_direct_snowflake:
                    hide_direct_snowflake_table(instance.table)
                else:
                    hide_direct_mysql_table(instance.table)
        elif enabled_columns_changed and instance.table is not None and instance.should_sync:
            # Warehouse mode: hide newly-disabled columns from HogQL immediately. Restoration
            # (reset to None or re-enabling a column) is deferred to the next sync — Delta may
            # not contain the column yet, so exposing it now would surface all-NULL queries.
            current_columns = instance.table.columns or {}
            projected_columns = _filter_dwh_columns_by_enabled_columns(
                current_columns,
                validated_data["enabled_columns"],
                instance.primary_key_columns,
                instance.incremental_field,
            )
            if projected_columns != current_columns:
                instance.table.columns = projected_columns
                instance.table.save(update_fields=["columns"])

        # CDC publication management: add/remove table when toggling should_sync
        is_cdc = (sync_type == ExternalDataSchema.SyncType.CDC) or (
            sync_type is None and instance.sync_type == ExternalDataSchema.SyncType.CDC
        )
        if is_cdc and source_type_supports_cdc(source.source_type):
            self._handle_cdc_publication_change(instance, source, should_sync, sync_type)

        if trigger_refresh:
            instance.sync_type_config.update({"reset_pipeline": True})
            validated_data["sync_type_config"].update({"reset_pipeline": True})

        # Persist under a row lock, replaying only the sync_type_config keys this request changed
        # so a concurrent CDC extract activity's writes aren't reverted by the full-instance save.
        updated_instance = self._save_merging_sync_type_config(instance, validated_data, original_sync_type_config)

        if source.supports_scheduled_sync and (
            should_sync is not None or was_sync_frequency_updated or was_sync_time_of_day_updated
        ):

            def update_schedule() -> None:
                should_sync_value = should_sync if should_sync is not None else updated_instance.should_sync
                schedule_exists = external_data_workflow_exists(str(updated_instance.id))

                if schedule_exists:
                    if should_sync is False:
                        pause_external_data_schedule(str(updated_instance.id))
                    elif should_sync is True:
                        unpause_external_data_schedule(str(updated_instance.id))
                elif should_sync_value:
                    # No schedule yet but the schema should be syncing — create (or recover) it. The
                    # schedule is built from the current frequency, so a cadence-only edit on an
                    # enabled-but-unscheduled schema still takes effect.
                    sync_external_data_job_workflow(updated_instance, create=True, should_sync=should_sync_value)

                # Re-issue an existing schedule when the cadence changed. A disabled schema with no
                # schedule has nothing to update — updating a missing schedule raises "workflow not
                # found" — so its new cadence is just saved and applies if/when it is enabled.
                if (was_sync_frequency_updated or was_sync_time_of_day_updated) and schedule_exists:
                    sync_external_data_job_workflow(updated_instance, create=False, should_sync=should_sync_value)

            self._run_temporal_side_effect(update_schedule)

        if trigger_refresh:
            self._run_temporal_side_effect(lambda: trigger_external_data_workflow(updated_instance))

        if sync_type == ExternalDataSchema.SyncType.WEBHOOK:
            self._maybe_create_webhook(updated_instance)

        # Sync CDC extraction schedule after any CDC schema change
        if is_cdc:

            def sync_cdc_schedule() -> None:
                try:
                    sync_cdc_extraction_schedule(source)
                except Exception as e:
                    logger.exception("Failed to sync CDC extraction schedule", exc_info=e)

            self._run_temporal_side_effect(sync_cdc_schedule)

        # If the cdc_table_mode change added a new physical write target, kick a full re-snapshot so the
        # new table is seeded from the current source state. `_seed_cdc_companion_from_snapshot` runs
        # automatically once the snapshot completes via `run_post_load_operations`.
        if is_cdc and "cdc_table_mode" in data:
            new_cdc_table_mode = data.get("cdc_table_mode")
            if _cdc_table_mode_change_needs_resnapshot(previous_cdc_table_mode, new_cdc_table_mode):
                logger.info(
                    "cdc_table_mode_changed_resnapshot_triggered",
                    schema_id=str(updated_instance.id),
                    old_cdc_table_mode=previous_cdc_table_mode,
                    new_cdc_table_mode=new_cdc_table_mode,
                )
                self._run_temporal_side_effect(lambda: _reset_cdc_for_full_resnapshot(updated_instance))

        return updated_instance

    def _is_webhook_only_schema(self, schema: ExternalDataSchema) -> bool:
        source = schema.source
        if not source.job_inputs:
            return False
        try:
            source_type = ExternalDataSourceType(source.source_type)
            source_impl = SourceRegistry.get_source(source_type)
        except Exception:
            return False
        try:
            config = source_impl.parse_config(source.job_inputs)
            source_schemas = source_impl.get_schemas(config, schema.team_id, names=[schema.name])
        except Exception:
            return False
        return any(s.name == schema.name and s.webhook_only for s in source_schemas)

    def _xmin_available_for_schema(self, schema: ExternalDataSchema) -> bool:
        """True when the source advertises xmin support for this table (Postgres heap table or
        materialized view, PG13+). Runs discovery so a raw PATCH can't enable xmin on a table that
        has no physical `xmin` (plain views, foreign tables, partitioned parents)."""
        source = schema.source
        if not source.job_inputs:
            return False
        try:
            source_type = ExternalDataSourceType(source.source_type)
            source_impl = SourceRegistry.get_source(source_type)
            config = source_impl.parse_config(source.job_inputs)
            source_schemas = source_impl.get_schemas(config, schema.team_id, names=[schema.name])
        except Exception:
            return False
        return any(s.name == schema.name and s.supports_xmin for s in source_schemas)

    def warm_webhook_only_check(self, instance: ExternalDataSchema) -> None:
        """Pre-run the webhook-only validation that reaches the external source, caching the result.

        `_is_webhook_only_schema` calls the source's `get_schemas`, which is a network round-trip (e.g.
        Google Ads OAuth refresh + field query). update() runs this same check, but bulk_update_schemas
        wraps each update() in a transaction — making the call there held the DB connection idle-in-
        transaction long enough for the server to close it ("the connection is closed"). Calling this
        first (outside the transaction) does the network work up front; update() then reads the cached
        result and still raises per-schema, so failures stay isolated to one schema.
        """
        if self._webhook_only_check_applies():
            self._is_webhook_only_schema_cached(instance)

    def _webhook_only_check_applies(self) -> bool:
        # Single source of truth for when the webhook-only check runs, so update() and the
        # pre-transaction warm step can't drift apart and push the network call back into the
        # transaction. Reads `initial_data` (the raw request payload), like update() does.
        data = self.initial_data if isinstance(self.initial_data, dict) else {}
        return "sync_type" in data and data.get("sync_type") != ExternalDataSchema.SyncType.WEBHOOK

    def _is_webhook_only_schema_cached(self, schema: ExternalDataSchema) -> bool:
        if "_webhook_only_result" not in self.__dict__:
            self.__dict__["_webhook_only_result"] = self._is_webhook_only_schema(schema)
        return self.__dict__["_webhook_only_result"]

    def _maybe_create_webhook(self, schema: ExternalDataSchema) -> None:
        source = schema.source
        if not source.job_inputs:
            return

        try:
            source_type = ExternalDataSourceType(source.source_type)
            source_impl = SourceRegistry.get_source(source_type)
        except Exception as e:
            capture_exception(e)
            return

        if not isinstance(source_impl, WebhookSource):
            return

        config = source_impl.parse_config(source.job_inputs)
        source_schemas = source_impl.get_schemas(config, schema.team_id)
        webhook_source_schemas = {s.name for s in source_schemas if s.supports_webhooks}

        if schema.name not in webhook_source_schemas:
            return

        try:
            hog_fn_result = get_or_create_webhook_hog_function(
                team=schema.team,
                source=source_impl,
                source_id=str(source.pk),
                eligible_schemas=[schema],
            )

            if hog_fn_result.error or not hog_fn_result.hog_function:
                raise ValidationError(
                    f"Failed to set up webhook: {hog_fn_result.error or 'Unknown error'}. "
                    "You can set up the webhook manually from the Webhook tab."
                )

            if hog_fn_result.hog_function_created:
                # Only register the webhook if we're creating the hog function when it didn't exist previously
                result = create_and_register_webhook(source_impl, config, hog_fn_result, schema.team_id)
                if not result.success:
                    raise ValidationError(
                        f"Failed to register webhook on your source: {result.error or 'Unknown error'}. "
                        "You can set up the webhook manually from the Webhook tab."
                    )
            else:
                # Deferred to keep the provider call out of the surrounding transaction.
                # Fully non-fatal: the table is already enabled by the time this runs, so any
                # failure (bad creds, provider 403, network) must never propagate — it would
                # otherwise 500 the post-commit hook on the bulk path, or roll back the enable
                # on the single-update path. Data still flows once the user fixes provider events.
                def reconcile() -> None:
                    try:
                        reconcile_result = reconcile_webhook_events(
                            source_impl, config, hog_fn_result, schema.team_id, [schema.name]
                        )
                        if not reconcile_result.success:
                            logger.warning(
                                "Failed to reconcile webhook events on schema enable",
                                error=reconcile_result.error,
                                schema_id=str(schema.id),
                            )
                    except Exception as e:
                        logger.warning(
                            "Error reconciling webhook events on schema enable",
                            error=str(e),
                            schema_id=str(schema.id),
                        )

                self._run_temporal_side_effect(reconcile)
        except ValidationError:
            raise
        except Exception as e:
            logger.exception("Failed to create webhook during schema update", error=str(e))
            raise ValidationError(
                "Failed to create webhook. You can set up the webhook manually from the Webhook tab."
            ) from e

    def _handle_cdc_publication_change(
        self,
        instance: ExternalDataSchema,
        source: ExternalDataSource,
        should_sync: bool | None,
        sync_type: str | None,
    ) -> None:
        """Add/remove the table from the CDC capture set when a schema is toggled or set to CDC."""
        adapter = get_cdc_adapter(source)
        cdc_config = adapter.parse_cdc_config(source)
        if cdc_config.management_mode != "posthog" or not cdc_config.publication_name:
            return

        _, db_schema, source_table_name = get_postgres_source_location(
            schema_name=instance.name,
            schema_metadata=instance.schema_metadata,
            default_schema=(source.job_inputs or {}).get("schema"),
        )

        newly_set_to_cdc = (
            sync_type == ExternalDataSchema.SyncType.CDC and instance.sync_type != ExternalDataSchema.SyncType.CDC
        )

        # Add table to capture set when enabling CDC or toggling sync on
        if newly_set_to_cdc or (should_sync is True and not instance.should_sync):
            adapter.add_table(source, db_schema, source_table_name)

            # Always force a full re-snapshot on re-enable: while removed from the
            # publication the replication slot kept advancing, so any changes made
            # during that window are permanently lost regardless of how short it was.
            # reset_pipeline wipes the warehouse table first — otherwise the snapshot
            # merges current rows over the stale pre-disable ones and never drops deletes.
            if should_sync is True and not newly_set_to_cdc:
                # Mutate in memory only — the locked terminal save in `update()` (which calls this)
                # persists both fields, merging cdc_mode onto the freshly-read config so a concurrent
                # CDC extract activity's writes survive. A separate save here would clobber them.
                instance.sync_type_config["cdc_mode"] = "snapshot"
                instance.sync_type_config["reset_pipeline"] = True
                instance.initial_sync_complete = False

        # Remove table from capture set when toggling sync off
        elif should_sync is False and instance.should_sync:
            adapter.remove_table(source, db_schema, source_table_name)


class SimpleExternalDataSchemaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSchema
        fields = ["id", "name", "label", "should_sync", "last_synced_at", "sync_type"]


@extend_schema(extensions={"x-product": "warehouse_sources"})
class ExternalDataSchemaViewset(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "external_data_source"
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "reload",
        "resync",
        "cancel",
        "incremental_fields",
        "delete_data",
    ]
    scope_object_read_actions = ["list", "retrieve", "logs"]
    queryset = ExternalDataSchema.objects.all()
    serializer_class = ExternalDataSchemaSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["database"] = Database.create_for(team_id=self.team_id, user=cast(User, self.request.user))
        # Only the single-schema retrieve embeds the parent-source summary (see ExternalDataSchemaSerializer.get_source).
        context["include_source"] = self.action == "retrieve"
        return context

    def safely_get_queryset(self, queryset):
        # `table__external_data_source` is read on every schema serialization (SimpleTableSerializer
        # derives the dotted HogQL name from it), so join it for all actions to avoid a per-row query.
        queryset = (
            queryset.exclude(deleted=True).prefetch_related("created_by").select_related("table__external_data_source")
        )
        if self.action == "retrieve":
            # retrieve additionally embeds the source summary + table credential.
            queryset = queryset.select_related("source", "table__credential")
        return queryset.order_by(self.ordering)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSchema = self.get_object()

        if instance.table:
            instance.table.soft_delete()
        instance.soft_delete()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(parameters=[LogEntryRequestSerializer])
    @action(methods=["GET"], detail=True, filter_backends=[])
    def logs(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSchema = self.get_object()
        param_serializer = LogEntryRequestSerializer(data=request.query_params)
        if not param_serializer.is_valid():
            raise ValidationError(param_serializer.errors)
        params = param_serializer.validated_data
        data = fetch_log_entries(
            team_id=self.team_id,
            log_source="external_data_jobs",
            log_source_id=str(instance.id),
            limit=params["limit"],
            instance_id=params.get("instance_id"),
            after=params.get("after"),
            before=params.get("before"),
            search=params.get("search"),
            level=params["level"].split(",") if params.get("level") else None,
        )
        page = self.paginate_queryset(data)
        if page is not None:
            return self.get_paginated_response(LogEntrySerializer(page, many=True).data)
        return Response(LogEntrySerializer(data, many=True).data)

    @action(methods=["POST"], detail=True)
    def reload(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        if is_any_external_data_schema_paused(self.team_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        try:
            trigger_external_data_workflow(instance)
        except temporalio.service.RPCError as e:
            logger.exception(f"Could not trigger external data job for schema {instance.id}", exc_info=e)

        except Exception as e:
            logger.exception(f"Could not trigger external data job for schema {instance.id}", exc_info=e)
            raise

        instance.status = ExternalDataSchema.Status.RUNNING
        instance.save()
        return Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def resync(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        if is_any_external_data_schema_paused(self.team_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        latest_running_job = (
            ExternalDataJob.objects.filter(schema_id=instance.pk, team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )

        if latest_running_job and latest_running_job.workflow_id and latest_running_job.status == "Running":
            cancel_external_data_workflow(latest_running_job.workflow_id)

        cdc_resync = instance.is_cdc
        updates: dict[str, Any] = {"reset_pipeline": True}
        removes: list[str] = []
        if cdc_resync:
            # Reset CDC state so the next run does a full re-snapshot
            updates["cdc_mode"] = "snapshot"
            removes = ["cdc_last_log_position", "cdc_deferred_runs"]

        # Merge under a row lock so this reset can't clobber a concurrent CDC extract activity's
        # sync_type_config writes. Persist BEFORE triggering the workflow so the Postgres source
        # sees cdc_mode="snapshot" when it reloads the schema from DB — otherwise a race: the
        # workflow starts, loads stale "streaming" mode, raises CDCHandledExternally, and the
        # full-refresh never runs.
        # initial_sync_complete is saved in the same transaction as cdc_mode via extra_model_fields
        # so no reader can observe cdc_mode="snapshot" with initial_sync_complete=True.
        extra: dict[str, Any] = {"initial_sync_complete": False} if cdc_resync else {}
        instance.sync_type_config = update_sync_type_config_keys(
            instance.id, instance.team_id, updates=updates, removes=removes, extra_model_fields=extra
        )
        if cdc_resync:
            instance.initial_sync_complete = False
        instance.status = ExternalDataSchema.Status.RUNNING
        instance.save(update_fields=["status", "updated_at"])

        try:
            trigger_external_data_workflow(instance)
        except temporalio.service.RPCError as e:
            logger.exception(f"Could not trigger external data job for schema {instance.id}", exc_info=e)

        return Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def cancel(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        latest_running_job = (
            ExternalDataJob.objects.filter(schema_id=instance.pk, team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )

        if not latest_running_job or latest_running_job.status != "Running" or not latest_running_job.workflow_id:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"detail": "No running sync to cancel."},
            )

        try:
            cancel_external_data_workflow(latest_running_job.workflow_id)
        except temporalio.service.RPCError as e:
            logger.exception(f"Could not cancel external data workflow for schema {instance.id}", exc_info=e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"detail": "Could not find workflow to cancel. The sync may have already finished."},
            )

        return Response(status=status.HTTP_200_OK)

    @action(methods=["DELETE"], detail=True)
    def delete_data(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        if instance.source.is_direct_query:
            if instance.source.is_direct_postgres:
                hide_direct_postgres_table(instance.table)
            elif instance.source.is_direct_snowflake:
                hide_direct_snowflake_table(instance.table)
            else:
                hide_direct_mysql_table(instance.table)
            instance.should_sync = False
            instance.save(update_fields=["should_sync", "updated_at"])
            return Response(status=status.HTTP_200_OK)

        instance.delete_table()

        return Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def incremental_fields(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()
        source: ExternalDataSource = instance.source

        if not source.job_inputs:
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Missing job inputs"})

        if not source.source_type:
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Missing source type"})

        source_type_enum = ExternalDataSourceType(source.source_type)

        new_source = SourceRegistry.get_source(source_type_enum)
        config = new_source.parse_config(source.job_inputs)

        credentials_valid, credentials_error = new_source.validate_credentials(config, self.team_id, instance.name)
        if not credentials_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": credentials_error or "Invalid credentials"},
            )

        try:
            schemas = new_source.get_schemas(config, self.team_id, names=[instance.name])
        except Exception as e:
            capture_exception(e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": str(e)},
            )

        # Not every source honors the `names` filter (e.g. Slack returns all schemas regardless), so
        # `schemas` may contain unrelated tables in any order. Pick the one that matches this schema
        # instead of trusting `schemas[0]`, whose metadata could belong to a different table.
        schema = next((s for s in schemas if s.name == instance.name), None)
        if schema is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"message": f"Schema with name {instance.name} not found"}
            )

        # job_inputs is an EncryptedJSONField: booleans round-trip as "True"/"False"
        # strings, so bool(...) would treat "False" as truthy. str_to_bool decodes both.
        source_cdc_enabled = str_to_bool(source.job_inputs.get("cdc_enabled"))
        cdc_available = schema.supports_cdc if is_cdc_enabled_for_team(self.team) and source_cdc_enabled else None
        # xmin is Postgres-only AND flag-gated, mirroring the database_schema endpoint.
        xmin_available = (
            schema.supports_xmin
            if (source.source_type == ExternalDataSourceType.POSTGRES and is_xmin_enabled_for_team(self.team))
            else None
        )

        data = {
            "incremental_fields": schema.incremental_fields,
            "incremental_available": schema.supports_incremental,
            "append_available": schema.supports_append,
            "cdc_available": cdc_available,
            "xmin_available": xmin_available,
            "full_refresh_available": not schema.webhook_only,
            "supports_webhooks": schema.supports_webhooks,
            "webhook_only": schema.webhook_only,
            "available_columns": [
                {"field": col_name, "label": col_name, "type": col_type, "nullable": nullable}
                for col_name, col_type, nullable in schema.columns
            ],
            "detected_primary_keys": schema.detected_primary_keys,
        }

        return Response(status=status.HTTP_200_OK, data=data)
