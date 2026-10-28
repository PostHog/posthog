from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode

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
# Deployed cloud has no MSK Kafka table since 0248. There the WarpStream MV from 0247 is the only consumer
# and it already writes every model to the buffer, so the new model MV gets rows as soon as it exists.
# Ingestion is not touched there: if the WarpStream MV fails to insert, the consumer stops for every model.
# Nothing emits the new model until the intent topics pipeline is enabled, so no rows are lost before
# the model MV is created.
if run_mode().is_deployed_cloud:
    pause_ingestion: list[str] = []
    resume_ingestion: list[str] = []
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
