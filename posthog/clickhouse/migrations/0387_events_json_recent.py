from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    EVENTS_JSON_RECENT_MV_SQL,
    EVENTS_JSON_RECENT_TABLE_SQL,
    SHARDED_EVENTS_JSON_RECENT_TABLE_SQL,
    WRITABLE_EVENTS_JSON_RECENT_TABLE_SQL,
)
from posthog.run_mode import run_mode

# Cloud clusters get the native JSON events schema rolled out separately (see 0289), so this stays empty there.
operations = (
    []
    if run_mode().is_deployed_cloud
    else [
        run_sql_with_exceptions(SHARDED_EVENTS_JSON_RECENT_TABLE_SQL(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(EVENTS_JSON_RECENT_TABLE_SQL(), node_roles=[NodeRole.DATA]),
        # The MV fires on the inserts events_json_table_mv makes into writable_events_json on the events nodes.
        run_sql_with_exceptions(WRITABLE_EVENTS_JSON_RECENT_TABLE_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
        run_sql_with_exceptions(EVENTS_JSON_RECENT_MV_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
    ]
)
