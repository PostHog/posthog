from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ai.pg_embeddings import PG_EMBEDDINGS_TABLE_SQL

operations = [
    run_sql_with_exceptions(
        PG_EMBEDDINGS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
]
