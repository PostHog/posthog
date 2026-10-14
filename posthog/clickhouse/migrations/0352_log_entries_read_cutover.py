from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import LOG_ENTRIES_AUX_READER_SQL, LOG_ENTRIES_DATA_NODE_READERS_SQL
from posthog.clickhouse.log_entries_aux_readers import LOG_ENTRIES_AUX_JOIN_READERS_SQL
from posthog.run_mode import run_mode

# Codifies the log_entries read cutover: `log_entries` becomes the aux-cluster
# reader, and the main-cluster reader stays under `log_entries_distributed` as the
# rollback target.
#
# On the aux nodes the app-facing name is created directly (a no-op where it exists).
# The data nodes of deployed cloud regions already have this layout, so only
# non-deployed environments set it here. The statements are CREATE OR REPLACE of the
# target layout, not an EXCHANGE, so a run on a node that already has the layout
# changes nothing, even if the run_mode() gate resolves wrongly.
#
# A JOIN against `log_entries` runs on the aux nodes, so the aux nodes also get
# Distributed readers for the joined tables. The cloud regions already have them.
operations = [
    *[run_sql_with_exceptions(sql, node_roles=[NodeRole.AUX]) for sql in LOG_ENTRIES_AUX_JOIN_READERS_SQL()],
    run_sql_with_exceptions(LOG_ENTRIES_AUX_READER_SQL(), node_roles=[NodeRole.AUX]),
]

if not run_mode().is_deployed_cloud:
    operations += [
        run_sql_with_exceptions(sql, node_roles=[NodeRole.DATA]) for sql in LOG_ENTRIES_DATA_NODE_READERS_SQL()
    ]
