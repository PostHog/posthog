from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.indexed_embedding import (
    DOCUMENT_EMBEDDINGS_BUFFER_SHARDED_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_BUFFER_WRITABLE_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL,
    EMBEDDING_TABLES_1,
    KAFKA_TO_BUFFER_MV_SQL,
)

operations = [
    # Create the sharded buffer table on data nodes
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_BUFFER_SHARDED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
    ),
    # Create the writable distributed buffer table on ingestion nodes
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_BUFFER_WRITABLE_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # Create the MV that moves data from Kafka to writable buffer table
    run_sql_with_exceptions(
        KAFKA_TO_BUFFER_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]

# Create sharded tables with vector indexes first
for model_tables in EMBEDDING_TABLES_1:
    operations.append(
        run_sql_with_exceptions(
            model_tables.sharded_table_sql(),
            node_roles=[NodeRole.DATA],
            sharded=True,
        )
    )

# Add vector indexes to sharded tables (must be done after table creation)
# We create both L2 and cosine distance indexes to support either distance function
for model_tables in EMBEDDING_TABLES_1:
    for index_sql in model_tables.add_vector_index_sql():
        operations.append(
            run_sql_with_exceptions(
                index_sql,
                node_roles=[NodeRole.DATA],
                sharded=True,
                is_alter_on_replicated_table=True,
            )
        )

# Create distributed read tables
for model_tables in EMBEDDING_TABLES_1:
    operations.append(
        run_sql_with_exceptions(
            model_tables.distributed_table_sql(),
            node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        )
    )

# Create writable distributed tables
# Note: These are now on data nodes since the MVs that write to them are also on data nodes
# This keeps all buffer->model table processing local to data nodes, avoiding cross-node traffic
for model_tables in EMBEDDING_TABLES_1:
    operations.append(
        run_sql_with_exceptions(
            model_tables.writable_table_sql(),
            node_roles=[NodeRole.DATA],
        )
    )

# Finally, create materialized views to start consuming from the buffer
# Note: MVs are on data nodes where the buffer lives, so they read locally from the sharded buffer
# and write locally to the model-specific sharded tables via the writable distributed tables
for model_tables in EMBEDDING_TABLES_1:
    operations.append(
        run_sql_with_exceptions(
            model_tables.materialized_view_sql(),
            node_roles=[NodeRole.DATA],
        )
    )

# Create union view that combines all model-specific tables with model_name column
operations.append(
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    )
)
