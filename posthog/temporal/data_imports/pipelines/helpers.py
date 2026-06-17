from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from django.db.models import F

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.types import IncrementalFieldType
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

initial_datetime = datetime(1970, 1, 1, 0, 0, 0, 0, tzinfo=ZoneInfo("UTC"))


@database_sync_to_async_pool
def aget_external_data_job(team_id, job_id):
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    return ExternalDataJob.objects.get(id=job_id, team_id=team_id)


@database_sync_to_async_pool
def aupdate_job_count(job_id: str, team_id: int, count: int):
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    ExternalDataJob.objects.filter(id=job_id, team_id=team_id).update(rows_synced=F("rows_synced") + count)


def incremental_type_to_initial_value(field_type: IncrementalFieldType) -> int | datetime | date | str:
    if (
        field_type == IncrementalFieldType.Integer
        or field_type == IncrementalFieldType.Numeric
        or field_type == IncrementalFieldType.XID
    ):
        return 0
    if field_type == IncrementalFieldType.DateTime or field_type == IncrementalFieldType.Timestamp:
        return initial_datetime
    if field_type == IncrementalFieldType.Date:
        return date(1970, 1, 1)
    if field_type == IncrementalFieldType.ObjectID:
        return "000000000000000000000000"

    raise ValueError(f"Unsupported incremental field type: {field_type}")


def incremental_type_to_operator(field_type: IncrementalFieldType) -> str:
    # Date cursors lose all rows that land on the boundary day after the previous sync's
    # cursor advance, because the cursor only carries day-granularity and `>` skips
    # everything equal to that day. `>=` re-fetches the boundary day so primary-key dedup
    # (or append acceptance) can close the gap. Every other field type carries enough
    # resolution that `>` is safe and avoids re-shipping the boundary row on every sync.
    # xmin uses an inclusive lower bound (the previous run's snapshot ceiling) AND an
    # exclusive upper bound (this run's ceiling), so its lower comparison is `>=`.
    if field_type == IncrementalFieldType.Date or field_type == IncrementalFieldType.XID:
        return ">="
    return ">"


def build_table_name(source: ExternalDataSource, schema_name: str):
    # Dots in `schema_name` would parse as `<table>.<column>` in HogQL, so any source that ever
    # produces a dotted schema name (today: Postgres multi-schema like `public.auth_group`) needs
    # them rewritten. No-op for pre-existing single-schema sources whose names never contained dots.
    safe_schema_name = schema_name.replace(".", "__")
    return f"{source.prefix or ''}{source.source_type}_{safe_schema_name}".lower()


def sync_revenue_analytics_views(schema: ExternalDataSchema, source: ExternalDataSource) -> None:
    """Re-sync revenue analytics materialized views after a data load completes.

    Called after validate_schema_and_update_table links a DataWarehouseTable to the
    schema, so builders can now produce real queries instead of empty placeholders.
    """
    import structlog

    from products.data_modeling.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
    from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind
    from products.revenue_analytics.backend.views.orchestrator import SUPPORTED_SOURCES

    logger = structlog.get_logger(__name__)

    try:
        if not source.revenue_analytics_config_safe.enabled or source.source_type not in SUPPORTED_SOURCES:
            return

        managed_viewset = DataWarehouseManagedViewSet.objects.filter(
            team=schema.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        ).first()

        if managed_viewset is None:
            logger.warning(
                "sync_revenue_analytics_views_skipped_no_viewset",
                team_id=schema.team_id,
                source_id=str(source.id),
            )
            return

        logger.info(
            "sync_revenue_analytics_views_starting",
            team_id=schema.team_id,
            source_id=str(source.id),
            schema_name=schema.name,
        )
        managed_viewset.sync_views()
        logger.info(
            "sync_revenue_analytics_views_completed",
            team_id=schema.team_id,
            source_id=str(source.id),
        )
    except Exception as e:
        logger.exception(
            "sync_revenue_analytics_views_failed",
            team_id=schema.team_id,
            source_id=str(source.id),
            error=str(e),
        )
        capture_exception(e)
