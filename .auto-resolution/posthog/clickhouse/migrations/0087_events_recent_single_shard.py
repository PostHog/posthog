from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import DISTRIBUTED_EVENTS_RECENT_TABLE_SQL
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS distributed_events_recent ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(DISTRIBUTED_EVENTS_RECENT_TABLE_SQL()),
]
