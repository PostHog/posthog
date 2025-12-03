from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.precalculated_person_properties.sql import (
    DROP_OLD_PRECALCULATED_PERSON_PROPERTY_DISTRIBUTED_TABLE_SQL,
    DROP_OLD_PRECALCULATED_PERSON_PROPERTY_KAFKA_TABLE_SQL,
    DROP_OLD_PRECALCULATED_PERSON_PROPERTY_MV_SQL,
    DROP_OLD_PRECALCULATED_PERSON_PROPERTY_SHARDED_TABLE_SQL,
    DROP_OLD_PRECALCULATED_PERSON_PROPERTY_WRITABLE_TABLE_SQL,
    KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTIES_MV_SQL,
    PRECALCULATED_PERSON_PROPERTIES_SHARDED_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL,
)

operations = [
    # Drop old tables (singular naming) if they exist
    run_sql_with_exceptions(DROP_OLD_PRECALCULATED_PERSON_PROPERTY_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(
        DROP_OLD_PRECALCULATED_PERSON_PROPERTY_KAFKA_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(
        DROP_OLD_PRECALCULATED_PERSON_PROPERTY_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(DROP_OLD_PRECALCULATED_PERSON_PROPERTY_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_OLD_PRECALCULATED_PERSON_PROPERTY_SHARDED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    # Create new tables (plural naming)
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_SHARDED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(
        PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
]
