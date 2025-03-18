from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ai.pg_embeddings import (
    DROP_PG_EMBEDDINGS_TABLE_SQL,
    PG_EMBEDDINGS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(DROP_PG_EMBEDDINGS_TABLE_SQL(), node_role=NodeRole.DATA),
    run_sql_with_exceptions(DROP_PG_EMBEDDINGS_TABLE_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
    run_sql_with_exceptions(PG_EMBEDDINGS_TABLE_SQL(), node_role=NodeRole.ALL),
]
