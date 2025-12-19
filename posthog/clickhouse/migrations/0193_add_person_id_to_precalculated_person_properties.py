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


def CLEANUP_NULL_PERSON_IDS():
    """
    Delete rows with null person_id (00000000-0000-0000-0000-000000000000).
    These are rows that existed before the person_id column was added and cannot be used
    for person-based cohort queries.
    """
    return """
    ALTER TABLE sharded_precalculated_person_properties
    DELETE WHERE person_id = '00000000-0000-0000-0000-000000000000'
    """


operations = [
    # Step 1: Alter the sharded table to add person_id column
    run_sql_with_exceptions(ADD_PERSON_ID_TO_SHARDED_TABLE(), node_roles=[NodeRole.DATA], sharded=True),
    # Step 2: Clean up any rows with null person_ids (from before migration)
    run_sql_with_exceptions(CLEANUP_NULL_PERSON_IDS(), node_roles=[NodeRole.DATA], sharded=True),
    # Step 3: Recreate distributed tables (can't ALTER distributed tables - must drop/recreate)
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    run_sql_with_exceptions(
        PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    # Step 4: Recreate writable table (also distributed, so drop/recreate)
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(
        PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    # Step 5: Recreate Kafka table and materialized view with person_id
    run_sql_with_exceptions(DROP_PRECALCULATED_PERSON_PROPERTIES_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_KAFKA_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
]
