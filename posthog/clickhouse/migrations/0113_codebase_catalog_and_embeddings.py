from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from products.editor.backend.models.catalog import CODEBASE_CATALOG_TABLE_SQL
from products.editor.backend.models.embeddings import CODEBASE_EMBEDDINGS_TABLE_SQL


operations = [
    run_sql_with_exceptions(CODEBASE_CATALOG_TABLE_SQL(on_cluster=False), node_role=NodeRole.ALL),
    run_sql_with_exceptions(CODEBASE_EMBEDDINGS_TABLE_SQL(on_cluster=False), node_role=NodeRole.ALL),
]
