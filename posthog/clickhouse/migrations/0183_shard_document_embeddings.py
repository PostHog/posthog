from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.embedding import (
    DISTRIBUTED_DOCUMENT_EMBEDDINGS_TABLE_SQL,
    DOCUMENT_EMBEDDING_WRITABLE,
    DOCUMENT_EMBEDDINGS_MV,
    DOCUMENT_EMBEDDINGS_MV_SQL,
    DOCUMENT_EMBEDDINGS_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL,
    KAFKA_DOCUMENT_EMBEDDINGS,
    KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL,
)

# The only tricky part of this migration is that the behaviour of `DOCUMENT_EMBEDDINGS_TABLE_SQL` has changed -
# it now creates sharded tables rather than replicated tables. We don't drop the replicated table, as in production
# we want to keep the historical data around, at least until we get around to migrating it, but this does mean
# all future "rebuild the world" runs of the migration set will never create that old table, only the new sharded one.

operations = [
    # 1. Drop MV to stop processing messages from kafka
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DOCUMENT_EMBEDDINGS_MV}",
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 2. Drop Kafka table
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {KAFKA_DOCUMENT_EMBEDDINGS}",
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 3. Drop old writable table (but not the old "main" table, since we want to keep the data around)
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DOCUMENT_EMBEDDING_WRITABLE}",
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 4. Create new sharded data tables (this function used to create "posthog_document_embeddings" directly, but now creates the sharded_ version)
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
    ),
    # 5. Create distributed read table for the sharded data
    run_sql_with_exceptions(
        DISTRIBUTED_DOCUMENT_EMBEDDINGS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # 6. Create new writable distributed table pointing to sharded tables
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 7. Recreate Kafka table
    run_sql_with_exceptions(
        KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 8. Recreate MV writing to writable table (which now writes to sharded tables)
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
