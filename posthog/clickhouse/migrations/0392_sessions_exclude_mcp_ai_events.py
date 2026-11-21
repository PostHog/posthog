from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sessions_v2 import RAW_SESSION_TABLE_UPDATE_SQL
from posthog.models.raw_sessions.sessions_v3 import (
    RAW_SESSION_TABLE_MV_UPDATE_SQL_V3,
    RAW_SESSIONS_V3_EVENTS_WS_MV_UPDATE_SQL,
)
from posthog.run_mode import run_mode

# The sessions MVs stop reading $mcp_* and $ai_* events (see posthog/models/raw_sessions/excluded_events.py).
# Only the SELECT changes, so MODIFY QUERY keeps each MV attached to its source and ingestion does not stop.
# Rows written before this migration keep their values until a backfill rebuilds them.
#
# In cloud, raw_sessions_v3 is written by the WarpStream ingestion MV that 0328 creates on the ingestion-events
# nodes. 0178 dropped the v3 MVs on the data nodes there. Off cloud, the data-node MVs that 0100 and 0364 create
# write both tables.
#
# The cloud writer of raw_sessions (v2) is not changed here, because its placement in cloud is not declared in this
# repo. The ClickHouse team applies RAW_SESSION_TABLE_UPDATE_SQL to it by hand.
operations = (
    [
        run_sql_with_exceptions(
            RAW_SESSIONS_V3_EVENTS_WS_MV_UPDATE_SQL(),
            node_roles=[NodeRole.INGESTION_EVENTS],
            sharded=False,
            is_alter_on_replicated_table=False,
        ),
    ]
    if run_mode().is_deployed_cloud
    else [
        run_sql_with_exceptions(
            RAW_SESSION_TABLE_UPDATE_SQL(),
            node_roles=[NodeRole.DATA],
            sharded=False,
            is_alter_on_replicated_table=False,
        ),
        run_sql_with_exceptions(
            RAW_SESSION_TABLE_MV_UPDATE_SQL_V3(),
            node_roles=[NodeRole.DATA],
            sharded=False,
            is_alter_on_replicated_table=False,
        ),
    ]
)
