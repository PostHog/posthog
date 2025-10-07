from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import DISTRIBUTED_EVENTS_RECENT_TABLE_SQL

operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS distributed_events_recent ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
    ),
    run_sql_with_exceptions(DISTRIBUTED_EVENTS_RECENT_TABLE_SQL()),
]
