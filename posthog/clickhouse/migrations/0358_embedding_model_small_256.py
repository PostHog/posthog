from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.indexed_embedding import (
    DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL,
    EMBEDDING_TABLES_1,
    EMBEDDING_TABLES_2,
    KAFKA_TO_BUFFER_MV_SQL,
    drop_kafka_to_buffer_mv_sql,
    drop_union_view_sql,
)

# Mirrors 0191: pause the Kafka to buffer MV, create the model tables and their MV, rebuild the union
# view, resume ingestion. No vector index on purpose: the whole index would have to sit in memory.

operations = [
    run_sql_with_exceptions(
        drop_kafka_to_buffer_mv_sql(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]

for model_tables in EMBEDDING_TABLES_2:
    operations.append(
        run_sql_with_exceptions(
            model_tables.sharded_table_sql(),
            node_roles=[NodeRole.DATA],
            sharded=True,
        )
    )

for model_tables in EMBEDDING_TABLES_2:
    operations.append(
        run_sql_with_exceptions(
            model_tables.distributed_table_sql(),
            node_roles=[NodeRole.DATA],
        )
    )

for model_tables in EMBEDDING_TABLES_2:
    operations.append(
        run_sql_with_exceptions(
            model_tables.writable_table_sql(),
            node_roles=[NodeRole.DATA],
        )
    )

for model_tables in EMBEDDING_TABLES_2:
    operations.append(
        run_sql_with_exceptions(
            model_tables.materialized_view_sql(),
            node_roles=[NodeRole.DATA],
        )
    )

operations.extend(
    [
        run_sql_with_exceptions(
            drop_union_view_sql(),
            node_roles=[NodeRole.DATA],
        ),
        run_sql_with_exceptions(
            DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL([*EMBEDDING_TABLES_1, *EMBEDDING_TABLES_2]),
            node_roles=[NodeRole.DATA],
        ),
        run_sql_with_exceptions(
            KAFKA_TO_BUFFER_MV_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
    ]
)
