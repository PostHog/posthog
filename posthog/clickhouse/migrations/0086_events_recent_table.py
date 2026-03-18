from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import DISTRIBUTED_EVENTS_RECENT_TABLE_SQL, EVENTS_RECENT_TABLE_SQL

operations = [
    run_sql_with_exceptions(EVENTS_RECENT_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_EVENTS_RECENT_TABLE_SQL()),
]
