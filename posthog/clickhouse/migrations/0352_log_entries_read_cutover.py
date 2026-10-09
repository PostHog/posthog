from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import (
    LOG_ENTRIES_AUX_DISTRIBUTED_TABLE,
    LOG_ENTRIES_AUX_READER_SQL,
    LOG_ENTRIES_TABLE,
)
from posthog.clickhouse.log_entries_aux_readers import LOG_ENTRIES_AUX_JOIN_READERS_SQL
from posthog.run_mode import run_mode

# Codifies the log_entries read cutover: `log_entries` becomes the aux-cluster
# reader, and the pre-cutover main reader lives on under `log_entries_distributed`
# as the rollback handle.
#
# On the aux nodes the app-facing name is created directly (a no-op where the
# cutover already happened). On the data nodes of deployed cloud regions the swap
# is performed operationally per region with an atomic EXCHANGE, so only
# non-deployed environments run it here — that lands fresh environments in the
# same end state the cloud regions reach operationally.
#
# A JOIN against `log_entries` runs on the aux nodes, so the aux nodes also get
# Distributed readers for the joined tables. The cloud regions already have them.
operations = [
    *[run_sql_with_exceptions(sql, node_roles=[NodeRole.AUX]) for sql in LOG_ENTRIES_AUX_JOIN_READERS_SQL()],
    run_sql_with_exceptions(LOG_ENTRIES_AUX_READER_SQL(), node_roles=[NodeRole.AUX]),
]

if not run_mode().is_deployed_cloud:
    operations.append(
        run_sql_with_exceptions(
            f"EXCHANGE TABLES {LOG_ENTRIES_TABLE} AND {LOG_ENTRIES_AUX_DISTRIBUTED_TABLE}",
            node_roles=[NodeRole.DATA],
        )
    )
