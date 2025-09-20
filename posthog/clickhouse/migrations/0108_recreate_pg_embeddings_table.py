from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ai.pg_embeddings import PG_EMBEDDINGS_DATA_TABLE, PG_EMBEDDINGS_TABLE_SQL

_DROP_SYNC_PG_EMBEDDINGS_TABLE_SQL = f"DROP TABLE IF EXISTS {PG_EMBEDDINGS_DATA_TABLE()} SYNC"


operations = [
    # The table had an engine ReplacingMergeTree.
    run_sql_with_exceptions(_DROP_SYNC_PG_EMBEDDINGS_TABLE_SQL, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(
        PG_EMBEDDINGS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
]
