from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.batch_exports.backend.sql import (
    CREATE_EVENTS_BATCH_EXPORT_VIEW,
    CREATE_EVENTS_BATCH_EXPORT_VIEW_BACKFILL,
    CREATE_EVENTS_BATCH_EXPORT_VIEW_UNBOUNDED,
    CREATE_PERSONS_BATCH_EXPORT_VIEW,
)

operations = map(
    run_sql_with_exceptions,
    [
        CREATE_PERSONS_BATCH_EXPORT_VIEW,
        CREATE_EVENTS_BATCH_EXPORT_VIEW,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_UNBOUNDED,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_BACKFILL,
    ],
)
