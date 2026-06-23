from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.batch_exports.backend.sql import (
    CREATE_PERSONS_BATCH_EXPORT_VIEW,
    CREATE_PERSONS_BATCH_EXPORT_VIEW_BACKFILL,
)

operations = map(
    run_sql_with_exceptions,
    [
        CREATE_PERSONS_BATCH_EXPORT_VIEW,
        CREATE_PERSONS_BATCH_EXPORT_VIEW_BACKFILL,
    ],
)
