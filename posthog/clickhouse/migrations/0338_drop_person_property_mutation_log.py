from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Writers go first (MV, then Kafka table) so no insert targets a dropped table, then the
# Distributed proxy, then the aux storage table. The storage table exceeds the server's
# max_table_size_to_drop, so the drop overrides it per query.
operations = [
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS person_property_mutation_log_mv",
        node_roles=[NodeRole.INGESTION_EVENTS],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS kafka_person_property_mutation_log",
        node_roles=[NodeRole.INGESTION_EVENTS],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS person_property_mutation_log",
        node_roles=[NodeRole.AUX, NodeRole.DATA, NodeRole.INGESTION_EVENTS],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS person_property_mutation_log_data SETTINGS max_table_size_to_drop = 0",
        node_roles=[NodeRole.AUX],
    ),
]
