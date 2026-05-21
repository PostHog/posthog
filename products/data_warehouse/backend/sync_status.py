from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from django.db.models import Q

import humanize

from posthog.schema import DataWarehouseSyncWarning

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.table import DataWarehouseTable


# When a schema is still in RUNNING state but its last successful sync is older than
# (sync_frequency_interval * STALE_RUNNING_MULTIPLIER), we consider the data stale.
STALE_RUNNING_MULTIPLIER = 2

# Mirrors database._get_active_external_data_schemas / NOT_DELETED_Q. Kept local to avoid a
# circular import between sync_status.py and posthog.hogql.database.database.
_NOT_DELETED = Q(deleted=False) | Q(deleted__isnull=True)


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _active_external_data_schemas(warehouse_table: DataWarehouseTable) -> list[ExternalDataSchema]:
    preloaded = cast(
        list[ExternalDataSchema] | None,
        getattr(warehouse_table, "_active_external_data_schemas", None),
    )
    if preloaded is not None:
        return preloaded
    if warehouse_table.external_data_source_id is None:
        return []
    return list(ExternalDataSchema.objects.filter(_NOT_DELETED, table_id=warehouse_table.id))


def _build_warning_for_schema(
    *,
    table_name: str,
    schema: ExternalDataSchema,
    now: datetime,
) -> DataWarehouseSyncWarning | None:
    status = schema.status
    source_type = schema.source.source_type if schema.source_id else "unknown"

    def build(message: str) -> DataWarehouseSyncWarning:
        return DataWarehouseSyncWarning(
            table_name=table_name,
            schema_name=schema.name,
            source_type=source_type,
            status=status or ExternalDataSchema.Status.PAUSED,
            message=message,
        )

    if status == ExternalDataSchema.Status.FAILED:
        message = f"Last sync of `{table_name}` (from {source_type}) failed."
        if schema.last_synced_at:
            message += f" Results reflect data from {humanize.naturaltime(now - _ensure_utc(schema.last_synced_at))}."
        else:
            message += " No successful sync has completed yet — the table may be empty or incomplete."
        if schema.latest_error:
            message += f" Last error: {schema.latest_error}"
        return build(message)

    if status == ExternalDataSchema.Status.BILLING_LIMIT_REACHED:
        return build(
            f"Sync of `{table_name}` (from {source_type}) is paused because the data warehouse "
            "billing limit has been reached. Results may be out of date."
        )

    if status == ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW:
        return build(
            f"Sync of `{table_name}` (from {source_type}) is paused because the configured "
            "billing limit is too low. Results may be out of date."
        )

    if status == ExternalDataSchema.Status.PAUSED or not schema.should_sync:
        return build(
            f"Sync of `{table_name}` (from {source_type}) is paused. Results reflect the last successful sync."
        )

    if status == ExternalDataSchema.Status.RUNNING:
        interval = schema.sync_frequency_interval
        if interval is None or schema.last_synced_at is None:
            return None
        last_synced = _ensure_utc(schema.last_synced_at)
        if (now - last_synced) <= interval * STALE_RUNNING_MULTIPLIER:
            return None
        return build(
            f"`{table_name}` (from {source_type}) last completed syncing "
            f"{humanize.naturaltime(now - last_synced)}, more than twice its configured sync interval. "
            "A new sync is in progress but results may be out of date."
        )

    return None


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
