from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.batch_exports.backend.sql import CREATE_EVENTS_BATCH_EXPORT_VIEW_RECENT

operations = map(
    run_sql_with_exceptions,
    [
        CREATE_EVENTS_BATCH_EXPORT_VIEW_RECENT,
    ],
)
