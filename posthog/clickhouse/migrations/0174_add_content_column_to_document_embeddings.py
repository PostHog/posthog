from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.embedding import (
    DOCUMENT_EMBEDDING_WRITABLE,
    DOCUMENT_EMBEDDINGS_MV,
    DOCUMENT_EMBEDDINGS_MV_SQL,
    KAFKA_DOCUMENT_EMBEDDINGS,
    KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL,
    PARTITIONED_SHARDED_DOCUMENT_EMBEDDINGS,
)

ADD_CONTENT_COLUMN_SQL = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS content String DEFAULT ''
"""

operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DOCUMENT_EMBEDDINGS_MV}",
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {KAFKA_DOCUMENT_EMBEDDINGS}",
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 0183 is the migration that creates this table, so a replay of the migration set from an empty
    # cluster reaches this alter first. The table it creates already has the content column.
    run_sql_with_exceptions(
        ADD_CONTENT_COLUMN_SQL.format(table_name=PARTITIONED_SHARDED_DOCUMENT_EMBEDDINGS),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
        skip_if_table_missing=PARTITIONED_SHARDED_DOCUMENT_EMBEDDINGS,
    ),
    run_sql_with_exceptions(
        ADD_CONTENT_COLUMN_SQL.format(table_name=DOCUMENT_EMBEDDING_WRITABLE),
        node_roles=[NodeRole.INGESTION_SMALL],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
