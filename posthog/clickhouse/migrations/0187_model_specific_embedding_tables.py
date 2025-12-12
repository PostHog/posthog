from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.indexed_embedding import (
    DOCUMENT_EMBEDDINGS_BUFFER_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL,
    EMBEDDING_TABLES_1,
    KAFKA_TO_BUFFER_MV_SQL,
)

operations = [
    # Create the buffer table that receives all embeddings from Kafka
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_BUFFER_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # Create the MV that moves data from Kafka to buffer table
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
                is_alter_on_replicated_table=False,
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
for model_tables in EMBEDDING_TABLES_1:
    operations.append(
        run_sql_with_exceptions(
            model_tables.writable_table_sql(),
            node_roles=[NodeRole.INGESTION_SMALL],
        )
    )

# Finally, create materialized views to start consuming from Kafka
# These are brand new MVs so no need to drop anything first
for model_tables in EMBEDDING_TABLES_1:
    operations.append(
        run_sql_with_exceptions(
            model_tables.materialized_view_sql(),
            node_roles=[NodeRole.INGESTION_SMALL],
        )
    )

# Create union view that combines all model-specific tables with model_name column
operations.append(
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    )
)

# Note: The shared Kafka table is still created by the existing embedding.py setup
# Each model's MV filters from that shared stream by model_name
