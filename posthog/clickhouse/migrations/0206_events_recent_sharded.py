from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    DISTRIBUTED_SHARDED_EVENTS_RECENT_TABLE_SQL,
    SHARDED_EVENTS_RECENT_MV_SQL,
    SHARDED_EVENTS_RECENT_TABLE_SQL,
    WRITABLE_SHARDED_EVENTS_RECENT_TABLE_SQL,
)

operations = (
    [
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS events_recent_json_mv",
            node_roles=[NodeRole.DATA],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS writable_events_recent",
            node_roles=[NodeRole.DATA],
        ),
        # Create new sharded data table
        run_sql_with_exceptions(
            SHARDED_EVENTS_RECENT_TABLE_SQL(),
            node_roles=[NodeRole.DATA],
        ),
        # Create distributed read table
        run_sql_with_exceptions(
            DISTRIBUTED_SHARDED_EVENTS_RECENT_TABLE_SQL(),
            node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        ),
        # Create distributed write table
        run_sql_with_exceptions(
            WRITABLE_SHARDED_EVENTS_RECENT_TABLE_SQL(),
            node_roles=[NodeRole.DATA],
        ),
        # Create MV from sharded_events to writable_sharded_events_recent
        run_sql_with_exceptions(
            SHARDED_EVENTS_RECENT_MV_SQL(),
            node_roles=[NodeRole.DATA],
        ),
    ]
    if settings.CLOUD_DEPLOYMENT != "US"
    else []
)
