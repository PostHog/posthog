from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from posthog.schema import DataWarehouseSyncWarning

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.table import DataWarehouseTable


# When a schema is still in RUNNING state but its last successful sync is older than
# (sync_frequency_interval * STALE_RUNNING_MULTIPLIER), we consider the data stale.
STALE_RUNNING_MULTIPLIER = 2


def _format_relative(now: datetime, then: datetime) -> str:
    delta = now - then
    if delta < timedelta(minutes=1):
        return "less than a minute ago"
    if delta < timedelta(hours=1):
        minutes = int(delta.total_seconds() // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if delta < timedelta(days=1):
        hours = int(delta.total_seconds() // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = delta.days
    return f"{days} day{'s' if days != 1 else ''} ago"


def _build_warning_for_schema(
    *,
    table_name: str,
    schema: ExternalDataSchema,
    now: datetime,
) -> DataWarehouseSyncWarning | None:
    status = schema.status
    source_type = schema.source.source_type if schema.source_id else "unknown"

    def build(status_str: str, message: str) -> DataWarehouseSyncWarning:
        return DataWarehouseSyncWarning(
            table_name=table_name,
            schema_name=schema.name,
            source_type=source_type,
            status=status_str,
            message=message,
        )

    if status == ExternalDataSchema.Status.FAILED:
        message = f"Last sync of `{table_name}` (from {source_type}) failed."
        if schema.last_synced_at:
            message += f" Results reflect data from {_format_relative(now, _ensure_utc(schema.last_synced_at))}."
        else:
            message += " No successful sync has completed yet — the table may be empty or incomplete."
        if schema.latest_error:
            message += f" Last error: {schema.latest_error}"
        return build(str(status), message)

    if status == ExternalDataSchema.Status.BILLING_LIMIT_REACHED:
        return build(
            str(status),
            (
                f"Sync of `{table_name}` (from {source_type}) is paused because the data warehouse "
                "billing limit has been reached. Results may be out of date."
            ),
        )

    if status == ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW:
        return build(
            str(status),
            (
                f"Sync of `{table_name}` (from {source_type}) is paused because the configured "
                "billing limit is too low. Results may be out of date."
            ),
        )

    if status == ExternalDataSchema.Status.PAUSED or not schema.should_sync:
        return build(
            str(status or ExternalDataSchema.Status.PAUSED),
            (f"Sync of `{table_name}` (from {source_type}) is paused. Results reflect the last successful sync."),
        )

    if status == ExternalDataSchema.Status.RUNNING:
        interval = schema.sync_frequency_interval
        if interval is None or schema.last_synced_at is None:
            return None
        last_synced = _ensure_utc(schema.last_synced_at)
        threshold = interval * STALE_RUNNING_MULTIPLIER
        if (now - last_synced) <= threshold:
            return None
        return build(
            str(status),
            (
                f"`{table_name}` (from {source_type}) last completed syncing "
                f"{_format_relative(now, last_synced)}, more than twice its configured sync interval. "
                "A new sync is in progress but results may be out of date."
            ),
        )

    return None


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def get_warehouse_sync_warnings(
    warehouse_table: DataWarehouseTable,
    *,
    now: datetime | None = None,
) -> list[DataWarehouseSyncWarning]:
    """Return sync warnings for a single data warehouse table.

    Uses the table's preloaded `_active_external_data_schemas` when available; falls back to a query.
    Skips self-managed tables (no external data source).
    """
    from posthog.hogql.database.database import _get_active_external_data_schemas

    if warehouse_table.external_data_source_id is None:
        return []

    now = now or datetime.now(UTC)
    schemas = _get_active_external_data_schemas(warehouse_table)

    warnings: list[DataWarehouseSyncWarning] = []
    for schema in schemas:
        warning = _build_warning_for_schema(table_name=warehouse_table.name, schema=schema, now=now)
        if warning is not None:
            warnings.append(warning)

    return warnings
