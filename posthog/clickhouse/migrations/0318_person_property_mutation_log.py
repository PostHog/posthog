from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.person_property_mutation_sql import (
    PERSON_PROPERTY_MUTATION_LOG_DATA_TABLE_SQL,
    PERSON_PROPERTY_MUTATION_LOG_KAFKA_TABLE_SQL,
    PERSON_PROPERTY_MUTATION_LOG_MV_SQL,
    PERSON_PROPERTY_MUTATION_LOG_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(PERSON_PROPERTY_MUTATION_LOG_DATA_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(
        PERSON_PROPERTY_MUTATION_LOG_TABLE_SQL(), node_roles=[NodeRole.AUX, NodeRole.DATA, NodeRole.INGESTION_EVENTS]
    ),
    run_sql_with_exceptions(PERSON_PROPERTY_MUTATION_LOG_KAFKA_TABLE_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
    run_sql_with_exceptions(PERSON_PROPERTY_MUTATION_LOG_MV_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
]
