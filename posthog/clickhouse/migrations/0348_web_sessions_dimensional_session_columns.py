from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_sessions_sql import (
    DISTRIBUTED_WEB_SESSIONS_TABLE,
    SHARDED_WEB_SESSIONS_TABLE,
)

ADD_COLUMNS_SQL = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS entry_hostname String AFTER entry_pathname,
ADD COLUMN IF NOT EXISTS end_pathname String AFTER entry_hostname,
ADD COLUMN IF NOT EXISTS device_type String AFTER end_pathname,
ADD COLUMN IF NOT EXISTS os String AFTER device_type,
ADD COLUMN IF NOT EXISTS browser String AFTER os,
ADD COLUMN IF NOT EXISTS country_code String AFTER browser,
ADD COLUMN IF NOT EXISTS region_code String AFTER country_code,
ADD COLUMN IF NOT EXISTS city_name String AFTER region_code,
ADD COLUMN IF NOT EXISTS is_bounce Bool AFTER pageview_count,
ADD COLUMN IF NOT EXISTS session_duration Int64 AFTER is_bounce,
ADD COLUMN IF NOT EXISTS is_bot Bool AFTER session_duration,
ADD COLUMN IF NOT EXISTS paths Array(Tuple(host String, pathname String, pageviews UInt32)) AFTER is_bot
"""

operations = [
    run_sql_with_exceptions(
        ADD_COLUMNS_SQL.format(table_name=SHARDED_WEB_SESSIONS_TABLE()),
        node_roles=[NodeRole.AUX],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_COLUMNS_SQL.format(table_name=DISTRIBUTED_WEB_SESSIONS_TABLE()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_COLUMNS_SQL.format(table_name=DISTRIBUTED_WEB_SESSIONS_TABLE()),
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
