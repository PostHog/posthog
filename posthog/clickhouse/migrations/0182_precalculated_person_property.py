from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.precalculated_person_property.sql import (
    KAFKA_PRECALCULATED_PERSON_PROPERTY_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTY_DISTRIBUTED_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTY_MV_SQL,
    PRECALCULATED_PERSON_PROPERTY_SHARDED_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTY_WRITABLE_TABLE_SQL,
)

operations = [
    # Create sharded table on data nodes
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTY_SHARDED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    # Create distributed table on coordinator nodes
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTY_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    # Create Kafka table on ingestion layer
    run_sql_with_exceptions(KAFKA_PRECALCULATED_PERSON_PROPERTY_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    # Create writable distributed table on ingestion layer
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTY_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    # Create materialized view on ingestion layer
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTY_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
]
