from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode

from products.error_tracking.backend.embedding import (
    DOCUMENT_EMBEDDINGS_WS_MV_SQL,
    DROP_DOCUMENT_EMBEDDINGS_WS_MV_SQL,
    KAFKA_DOCUMENT_EMBEDDINGS_WS,
)
from products.error_tracking.backend.indexed_embedding import (
    DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL,
    EMBEDDING_TABLES_1,
    EMBEDDING_TABLES_2,
    KAFKA_TO_BUFFER_MV_SQL,
    drop_kafka_to_buffer_mv_sql,
)

# Mirrors 0191: pause ingestion, create the model tables and their MV, replace the union view, resume
# ingestion. No vector index on purpose: the whole index would have to sit in memory.
#
# Deployed cloud has no MSK Kafka table since 0248. There the WarpStream table from 0247 is the only
# consumer, and its MV writes only to the legacy table, so the buffer gets no rows. The Kafka to buffer
# MV from 0191 still reads the dropped MSK table, so it is dropped and recreated on the WarpStream
# table. Dropping both MVs stops the consumer, which then resumes from its committed offsets.
if run_mode().is_deployed_cloud:
    pause_ingestion = [drop_kafka_to_buffer_mv_sql(), DROP_DOCUMENT_EMBEDDINGS_WS_MV_SQL]
    # The legacy MV attaches first so that the legacy table, which readers still query, loses no rows.
    resume_ingestion = [DOCUMENT_EMBEDDINGS_WS_MV_SQL(), KAFKA_TO_BUFFER_MV_SQL(KAFKA_DOCUMENT_EMBEDDINGS_WS)]
else:
    pause_ingestion = [drop_kafka_to_buffer_mv_sql()]
    resume_ingestion = [KAFKA_TO_BUFFER_MV_SQL()]

operations = [run_sql_with_exceptions(sql, node_roles=[NodeRole.INGESTION_SMALL]) for sql in pause_ingestion]

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

operations.append(
    run_sql_with_exceptions(
        DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL([*EMBEDDING_TABLES_1, *EMBEDDING_TABLES_2], replace=True),
        node_roles=[NodeRole.DATA],
    )
)

operations.extend(run_sql_with_exceptions(sql, node_roles=[NodeRole.INGESTION_SMALL]) for sql in resume_ingestion)
