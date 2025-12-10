from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.embedding import (
    DISTRIBUTED_DOCUMENT_EMBEDDINGS_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_MV_SQL,
    DOCUMENT_EMBEDDINGS_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL,
    DROP_DISTRIBUTED_DOCUMENT_EMBEDDINGS_SQL,
    DROP_DOCUMENT_EMBEDDINGS_MV_SQL,
    DROP_DOCUMENT_EMBEDDINGS_WRITABLE_SQL,
)

operations = [
    # 1. Drop MV to stop consuming from Kafka
    run_sql_with_exceptions(
        DROP_DOCUMENT_EMBEDDINGS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 2. Create new partitioned sharded table with TTL
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
    ),
    # 3. Drop existing distributed read table
    run_sql_with_exceptions(
        DROP_DISTRIBUTED_DOCUMENT_EMBEDDINGS_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # 4. Drop existing writable distributed table
    run_sql_with_exceptions(
        DROP_DOCUMENT_EMBEDDINGS_WRITABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 5. Recreate distributed read table pointing to partitioned sharded table
    run_sql_with_exceptions(
        DISTRIBUTED_DOCUMENT_EMBEDDINGS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # 6. Recreate writable distributed table pointing to partitioned sharded table
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 7. Recreate MV to resume consuming from Kafka
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
