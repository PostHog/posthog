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
    ALTER TABLE sharded_precalculated_person_properties
    ADD COLUMN IF NOT EXISTS person_id UUID AFTER distinct_id
    """


operations = [
    # Step 1: Drop materialized view (most dependent)
    run_sql_with_exceptions(DROP_PRECALCULATED_PERSON_PROPERTIES_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    # Step 2: Drop Kafka table
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_KAFKA_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    # Step 3: Drop writable table
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    # Step 4: Drop distributed table
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    # Step 5: Alter the sharded table to add person_id column
    run_sql_with_exceptions(
        ADD_PERSON_ID_TO_SHARDED_TABLE(), node_roles=[NodeRole.DATA], sharded=True, is_alter_on_replicated_table=True
    ),
    # Step 6: Recreate distributed table
    run_sql_with_exceptions(
        PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    # Step 7: Recreate writable table
    run_sql_with_exceptions(
        PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    # Step 8: Recreate Kafka table
    run_sql_with_exceptions(KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    # Step 9: Recreate materialized view
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
]
