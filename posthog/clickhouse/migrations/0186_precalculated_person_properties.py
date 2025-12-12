from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.precalculated_person_properties.sql import (
    KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTIES_MV_SQL,
    PRECALCULATED_PERSON_PROPERTIES_SHARDED_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL,
)

operations = [
    # Create precalculated_person_properties tables with distinct_id
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_SHARDED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(
        PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
]
