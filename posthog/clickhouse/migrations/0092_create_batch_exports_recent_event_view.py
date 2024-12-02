from posthog.batch_exports.sql import (
    CREATE_EVENTS_BATCH_EXPORT_VIEW_RECENT,
)
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = map(
    run_sql_with_exceptions,
    [
        CREATE_EVENTS_BATCH_EXPORT_VIEW_RECENT,
    ],
)
