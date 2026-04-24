from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.precalculated_events.sql import (
    KAFKA_PRECALCULATED_EVENTS_WS_TABLE_SQL,
    PRECALCULATED_EVENTS_WS_MV_SQL,
)
from posthog.models.precalculated_person_properties.sql import (
    KAFKA_PRECALCULATED_PERSON_PROPERTIES_WS_TABLE_SQL,
    PRECALCULATED_PERSON_PROPERTIES_WS_MV_SQL,
)

# Migration to create WarpStream Kafka engine tables for the precalculated topics.
#
# These coexist alongside the existing MSK Kafka engine tables, reading from the same
# topics (clickhouse_prefiltered_events, clickhouse_precalculated_person_properties)
# but via the warpstream_calculated_events named collection. Each has its own consumer
# group to avoid conflicts with the MSK tables.
#
# New tables (all INGESTION_MEDIUM):
# - kafka_precalculated_events_ws + precalculated_events_ws_mv
# - kafka_precalculated_person_properties_ws + precalculated_person_properties_ws_mv

operations = [
    run_sql_with_exceptions(
        KAFKA_PRECALCULATED_EVENTS_WS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        PRECALCULATED_EVENTS_WS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        KAFKA_PRECALCULATED_PERSON_PROPERTIES_WS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        PRECALCULATED_PERSON_PROPERTIES_WS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
]
