from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import EVENTS_TABLE_SQL
from posthog.settings import CLICKHOUSE_DATABASE

operations = [
    run_sql_with_exceptions(f"CREATE DATABASE IF NOT EXISTS {CLICKHOUSE_DATABASE}", node_roles=NodeRole.ALL),
    run_sql_with_exceptions(EVENTS_TABLE_SQL(), node_roles=NodeRole.DATA),
]
