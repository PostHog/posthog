from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# The ClickHouse team drops the column on the clusters first, so in cloud these are no-ops that bring the repo schema in line.
# The distributed tables go before the sharded table so that no read table names a column its shards no longer have.

operations = [
    run_sql_with_exceptions(
        "ALTER TABLE session_replay_events DROP COLUMN IF EXISTS surfacing_score",
        node_roles=[NodeRole.DATA, NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        "ALTER TABLE sharded_session_replay_events DROP COLUMN IF EXISTS surfacing_score",
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
