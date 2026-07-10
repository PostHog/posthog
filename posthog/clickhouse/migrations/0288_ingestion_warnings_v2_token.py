from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ingestion_warnings.sql_v2 import DISTRIBUTED_TABLE_NAME, TABLE_NAME

# Adds a `token` column (derived from the `details` JSON) so producers that only know the
# API token (e.g. capture, which has no database access) can emit warnings with team_id=0
# and have the read side match them to a team by token. Bloom-filter indexed because token
# lookups can't use the (team_id, type, timestamp) primary key.
ADD_TOKEN_COLUMN = (
    "ALTER TABLE {table} "
    "ADD COLUMN IF NOT EXISTS token LowCardinality(String) DEFAULT JSONExtractString(details, 'token') "
    "AFTER person_id"
)

operations = [
    run_sql_with_exceptions(
        ADD_TOKEN_COLUMN.format(table=TABLE_NAME),
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {TABLE_NAME} ADD INDEX IF NOT EXISTS idx_token token TYPE bloom_filter(0.01) GRANULARITY 1",
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {TABLE_NAME} MATERIALIZE INDEX idx_token",
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_TOKEN_COLUMN.format(table=DISTRIBUTED_TABLE_NAME),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
