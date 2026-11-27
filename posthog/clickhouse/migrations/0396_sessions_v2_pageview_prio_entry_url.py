from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sessions_v2 import RAW_SESSION_TABLE_UPDATE_SQL
from posthog.run_mode import run_mode

# The raw_sessions MV takes entry_url, end_url and the attribution columns from pageviews and screens first, then
# from events that have a URL.
# Only the SELECT changes and the aggregate state types stay the same, so MODIFY QUERY keeps the MV attached to its
# source and existing rows stay readable. Rows written before this migration keep their values until a backfill.
#
# The cloud writer of raw_sessions is not declared in this repo, so this migration does not change it. The ClickHouse
# team applies RAW_SESSION_TABLE_UPDATE_SQL to it by hand.
operations = (
    []
    if run_mode().is_deployed_cloud
    else [
        run_sql_with_exceptions(
            RAW_SESSION_TABLE_UPDATE_SQL(),
            node_roles=[NodeRole.DATA],
            sharded=False,
            is_alter_on_replicated_table=False,
        ),
    ]
)
