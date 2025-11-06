from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.embedding import (
    DOCUMENT_EMBEDDING_WRITABLE,
    DOCUMENT_EMBEDDINGS,
    DOCUMENT_EMBEDDINGS_MV,
    DOCUMENT_EMBEDDINGS_MV_SQL,
    KAFKA_DOCUMENT_EMBEDDINGS,
    KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL,
)

ADD_CONTENT_COLUMN_SQL = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS content String DEFAULT ''
"""

operations = [
    # 1. Drop materialized view
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DOCUMENT_EMBEDDINGS_MV}",
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 2. Drop kafka table
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {KAFKA_DOCUMENT_EMBEDDINGS}",
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 3. Add column to main table
    run_sql_with_exceptions(
        ADD_CONTENT_COLUMN_SQL.format(table_name=DOCUMENT_EMBEDDINGS),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # 4. Add column to writable table
    run_sql_with_exceptions(
        ADD_CONTENT_COLUMN_SQL.format(table_name=DOCUMENT_EMBEDDING_WRITABLE),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 5. Recreate kafka table
    run_sql_with_exceptions(
        KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 6. Recreate materialized view
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
