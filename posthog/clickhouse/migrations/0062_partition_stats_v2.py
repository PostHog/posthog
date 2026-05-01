from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import (
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
)
from posthog.models.kafka_partition_stats.sql import (
    PartitionStatsKafkaTable as KafkaTable,
    PartitionStatsV2MaterializedView as MaterializedView,
    PartitionStatsV2Table as Table,
)
from posthog.settings.kafka import KAFKA_HOSTS

# Session recording snapshot Kafka tables that this migration originally created against
# SESSION_RECORDING_KAFKA_HOSTS have been removed; fresh installs no longer get those MVs.
table = Table()

existing_kafka_tables = [
    # 0041 added KAFKA_EVENTS_PLUGIN_INGESTION
    KafkaTable(KAFKA_HOSTS, KAFKA_EVENTS_PLUGIN_INGESTION),
    # 0042 added KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW
    KafkaTable(KAFKA_HOSTS, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW),
]

new_kafka_tables = [
    KafkaTable(KAFKA_HOSTS, KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL),
]

operations = [
    run_sql_with_exceptions(table.get_create_table_sql()),
]

for kafka_table in existing_kafka_tables:
    operations.append(run_sql_with_exceptions(MaterializedView(table, kafka_table).get_create_table_sql()))

for kafka_table in new_kafka_tables:
    operations.extend(
        [
            run_sql_with_exceptions(kafka_table.get_create_table_sql()),
            run_sql_with_exceptions(MaterializedView(table, kafka_table).get_create_table_sql()),
        ]
    )
