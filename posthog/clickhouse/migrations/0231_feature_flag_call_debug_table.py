from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.feature_flag_call_debug.sql import DATA_TABLE_SQL, DISTRIBUTED_TABLE_SQL, KAFKA_TABLE_SQL, MV_SQL

operations = [
    # Sharded data table on data nodes
    run_sql_with_exceptions(
        DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Distributed table on data nodes (for querying)
    run_sql_with_exceptions(
        DISTRIBUTED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Kafka consumer table on ingestion layer
    run_sql_with_exceptions(
        KAFKA_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # Materialized view on ingestion layer
    run_sql_with_exceptions(
        MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
