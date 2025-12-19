from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.precalculated_person_properties.sql import (
    DROP_PRECALCULATED_PERSON_PROPERTIES_KAFKA_TABLE_SQL,
    DROP_PRECALCULATED_PERSON_PROPERTIES_MV_SQL,
    KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTIES_MV_SQL,
)


def ADD_PERSON_ID_TO_SHARDED_TABLE():
    return """
    ALTER TABLE sharded_precalculated_person_properties
    ADD COLUMN IF NOT EXISTS person_id UUID AFTER distinct_id
    """


def ADD_PERSON_ID_TO_DISTRIBUTED_TABLE():
    return """
    ALTER TABLE precalculated_person_properties
    ADD COLUMN IF NOT EXISTS person_id UUID AFTER distinct_id
    """


def ADD_PERSON_ID_TO_WRITABLE_TABLE():
    return """
    ALTER TABLE writable_precalculated_person_properties
    ADD COLUMN IF NOT EXISTS person_id UUID AFTER distinct_id
    """


operations = [
    # Add person_id column to sharded table (replicated sharded table)
    run_sql_with_exceptions(ADD_PERSON_ID_TO_SHARDED_TABLE(), node_roles=[NodeRole.DATA], sharded=True),
    # Add person_id column to distributed tables
    run_sql_with_exceptions(ADD_PERSON_ID_TO_DISTRIBUTED_TABLE(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(ADD_PERSON_ID_TO_WRITABLE_TABLE(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    # Recreate Kafka table and materialized view with person_id
    run_sql_with_exceptions(DROP_PRECALCULATED_PERSON_PROPERTIES_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_KAFKA_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
]
