from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import EVENTS_RECENT_DATA_TABLE, EVENTS_RECENT_TABLE_SQL

operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {EVENTS_RECENT_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' SYNC"
    ),
    run_sql_with_exceptions(EVENTS_RECENT_TABLE_SQL()),
]
