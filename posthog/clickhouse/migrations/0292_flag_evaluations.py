from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import (
    DISTRIBUTED_FLAG_EVALUATIONS_TABLE_SQL,
    FLAG_EVALUATIONS_MV_SQL,
    FLAG_EVALUATIONS_TABLE_SQL,
    KAFKA_FLAG_EVALUATIONS_TABLE_SQL,
    WRITABLE_FLAG_EVALUATIONS_TABLE_SQL,
)

operations = [
    # 1. Sharded data table on the main cluster
    run_sql_with_exceptions(
        FLAG_EVALUATIONS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # 2. Writable Distributed on the ingestion layer, fanning out to shards
    run_sql_with_exceptions(
        WRITABLE_FLAG_EVALUATIONS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # 3. Distributed read table on data nodes
    run_sql_with_exceptions(
        DISTRIBUTED_FLAG_EVALUATIONS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # 4. Kafka engine table on the ingestion layer
    run_sql_with_exceptions(
        KAFKA_FLAG_EVALUATIONS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # 5. MV last, once its source and target exist
    run_sql_with_exceptions(
        FLAG_EVALUATIONS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
]
