from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.precalculated_person_properties.sql import (
    DROP_PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL,
    DROP_PRECALCULATED_PERSON_PROPERTIES_KAFKA_TABLE_SQL,
    DROP_PRECALCULATED_PERSON_PROPERTIES_MV_SQL,
    DROP_PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL,
    KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTIES_MV_SQL,
    PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL,
)


def ADD_PERSON_ID_TO_SHARDED_TABLE():
    return """
    ALTER TABLE IF EXISTS sharded_precalculated_person_properties
    ADD COLUMN person_id UUID AFTER distinct_id
    """


operations = [
    # Step 1: Alter the sharded table to add person_id column
    run_sql_with_exceptions(
        ADD_PERSON_ID_TO_SHARDED_TABLE(), node_roles=[NodeRole.DATA], sharded=True, is_alter_on_replicated_table=True
    ),
    # Step 2: Recreate distributed tables (can't ALTER distributed tables - must drop/recreate)
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    run_sql_with_exceptions(
        PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    # Step 3: Recreate writable table (also distributed, so drop/recreate)
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(
        PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    # Step 4: Recreate Kafka table and materialized view with person_id
    run_sql_with_exceptions(DROP_PRECALCULATED_PERSON_PROPERTIES_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_KAFKA_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
]
