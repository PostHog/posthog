from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.signals.backend.embedding_table import (
    DOCUMENT_EMBEDDING_WRITABLE,
    DOCUMENT_EMBEDDINGS,
    DOCUMENT_EMBEDDINGS_MV,
    DOCUMENT_EMBEDDINGS_MV_SQL,
    KAFKA_DOCUMENT_EMBEDDINGS,
    KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL,
)

ADD_METADATA_COLUMN_SQL = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS metadata String DEFAULT '{}'
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
    run_sql_with_exceptions(
        ADD_METADATA_COLUMN_SQL.format(table_name=DOCUMENT_EMBEDDINGS),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_METADATA_COLUMN_SQL.format(table_name=DOCUMENT_EMBEDDING_WRITABLE),
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
