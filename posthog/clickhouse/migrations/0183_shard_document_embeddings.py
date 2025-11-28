from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.embedding import (
    DISTRIBUTED_DOCUMENT_EMBEDDINGS_TABLE_SQL,
    DOCUMENT_EMBEDDING_WRITABLE,
    DOCUMENT_EMBEDDINGS_DATA_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_MV,
    DOCUMENT_EMBEDDINGS_MV_SQL,
    DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL,
    KAFKA_DOCUMENT_EMBEDDINGS,
    KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL,
)

operations = [
    # 1. Drop MV
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DOCUMENT_EMBEDDINGS_MV}",
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 2. Drop Kafka table
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {KAFKA_DOCUMENT_EMBEDDINGS}",
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 3. Drop old writable table
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DOCUMENT_EMBEDDING_WRITABLE}",
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 4. Create new sharded data table
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
    ),
    # 5. Create distributed read table for the sharded data
    run_sql_with_exceptions(
        DISTRIBUTED_DOCUMENT_EMBEDDINGS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # 6. Create new writable distributed table pointing to sharded table
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 7. Recreate Kafka table
    run_sql_with_exceptions(
        KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 8. Recreate MV writing to writable table (which now writes to sharded table)
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
