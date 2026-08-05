from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from django.db.models import Q

import humanize

from products.warehouse_sources.backend.facade.models import ExternalDataSchema

if TYPE_CHECKING:
    from posthog.schema import DataWarehouseSyncWarning

    from products.warehouse_sources.backend.facade.models import DataWarehouseTable


# When a schema is still in RUNNING state but its last successful sync is older than
# (sync_frequency_interval * STALE_RUNNING_MULTIPLIER), we consider the data stale.
STALE_RUNNING_MULTIPLIER = 2

# Mirrors database._get_active_external_data_schemas / NOT_DELETED_Q. Kept local to avoid a
# circular import between sync_status.py and posthog.hogql.database.database.
_NOT_DELETED = Q(deleted=False) | Q(deleted__isnull=True)


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _is_stale(schema: ExternalDataSchema, now: datetime) -> bool:
    """Stale once the last sync is older than 2x the cadence; unknown cadence or never-synced is not stale."""
    interval = schema.sync_frequency_interval
    if interval is None or schema.last_synced_at is None:
        return False
    return (now - _ensure_utc(schema.last_synced_at)) > interval * STALE_RUNNING_MULTIPLIER


def _active_external_data_schemas(warehouse_table: DataWarehouseTable) -> list[ExternalDataSchema]:
    preloaded = cast(
        list[ExternalDataSchema] | None,
        getattr(warehouse_table, "_active_external_data_schemas", None),
    )
    if preloaded is not None:
        return preloaded
    if warehouse_table.external_data_source_id is None:
        return []
    # select_related("source"): _build_warning_for_schema reads schema.source.source_type.
    return list(ExternalDataSchema.objects.filter(_NOT_DELETED, table_id=warehouse_table.id).select_related("source"))


def _build_warning_for_schema(
    *,
    table_name: str,
    schema: ExternalDataSchema,
    now: datetime,
) -> DataWarehouseSyncWarning | None:
    # Deferred: posthog.schema (the pydantic models) stays off django.setup(), where this
    # module loads in every process via the warehouse table model.
    from posthog.schema import DataWarehouseSyncWarning  # noqa: PLC0415

    schema_status = schema.status
    source_type = schema.source.source_type if schema.source_id else "unknown"
    source_id = str(schema.source_id) if schema.source_id else None

    def build(*, status: str, message: str) -> DataWarehouseSyncWarning:
        return DataWarehouseSyncWarning(
            table_name=table_name,
            schema_name=schema.name,
            source_type=source_type,
            source_id=source_id,
            status=status,
            message=message,
        )

    if schema_status == ExternalDataSchema.Status.FAILED:
        message = f"Last sync of `{table_name}` (from {source_type}) failed."
        if schema.last_synced_at:
            message += f" Results reflect data from {humanize.naturaltime(now - _ensure_utc(schema.last_synced_at))}."
        else:
            message += " No successful sync has completed yet — the table may be empty or incomplete."
        # Deliberately omit schema.latest_error: it holds raw exception text (DB hostnames,
        # credentials, stack traces) and this message reaches LLM contexts via MCP/Max. The full
        # error stays in the data warehouse source screen, which is access-scoped.
        message += " Check the data warehouse source for details."
        return build(status=ExternalDataSchema.Status.FAILED, message=message)

    if schema_status == ExternalDataSchema.Status.BILLING_LIMIT_REACHED:
        return build(
            status=ExternalDataSchema.Status.BILLING_LIMIT_REACHED,
            message=(
                f"Sync of `{table_name}` (from {source_type}) is paused because the data warehouse "
                "billing limit has been reached. Results may be out of date."
            ),
        )

    if schema_status == ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW:
        return build(
            status=ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW,
            message=(
                f"Sync of `{table_name}` (from {source_type}) is paused because the configured "
                "billing limit is too low. Results may be out of date."
            ),
        )

    if schema_status == ExternalDataSchema.Status.PAUSED or not schema.should_sync:
        if schema.last_synced_at is None:
            message = (
                f"Sync of `{table_name}` (from {source_type}) is paused and hasn't completed a sync yet "
                "— the table may be empty or incomplete."
            )
        else:
            ago = humanize.naturaltime(now - _ensure_utc(schema.last_synced_at))
            if _is_stale(schema, now):
                message = (
                    f"Sync of `{table_name}` (from {source_type}) is paused. "
                    f"Results reflect the last successful sync from {ago}."
                )
            else:
                message = (
                    f"Sync of `{table_name}` (from {source_type}) is paused — results are current as of "
                    f"{ago}, but won't update until syncing is re-enabled."
                )
        return build(status=ExternalDataSchema.Status.PAUSED, message=message)

    # Enabled and healthy: warn only once data is actually stale (covers RUNNING and idle COMPLETED).
    last_synced = schema.last_synced_at
    if last_synced is None or not _is_stale(schema, now):
        return None

    ago = humanize.naturaltime(now - _ensure_utc(last_synced))
    if schema_status == ExternalDataSchema.Status.RUNNING:
        message = (
            f"`{table_name}` (from {source_type}) last completed syncing {ago}, more than twice its "
            "configured sync interval. A new sync is in progress but results may be out of date."
        )
    else:
        message = (
            f"`{table_name}` (from {source_type}) last synced {ago}, more than twice its configured "
            "sync interval. Results may be out of date."
        )
    return build(status=schema_status or ExternalDataSchema.Status.RUNNING, message=message)


def get_warehouse_sync_warnings(
    warehouse_table: DataWarehouseTable,
    *,
    now: datetime,
) -> list[DataWarehouseSyncWarning]:
    """Return sync warnings for a single data warehouse table.

    Uses the table's preloaded `_active_external_data_schemas` when available; falls back to a query.
    Skips self-managed tables (no external data source). Caller must pass `now` so a single timestamp
    is shared across all tables in a build.
    """
    if warehouse_table.external_data_source_id is None:
        return []

    warnings: list[DataWarehouseSyncWarning] = []
    for schema in _active_external_data_schemas(warehouse_table):
        warning = _build_warning_for_schema(table_name=warehouse_table.name, schema=schema, now=now)
        if warning is not None:
            warnings.append(warning)
    return warnings
