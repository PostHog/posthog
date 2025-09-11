from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import (
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW,
)
from posthog.models.kafka_partition_stats.sql import (
    PartitionStatsKafkaTable as KafkaTable,
    PartitionStatsV2MaterializedView as MaterializedView,
    PartitionStatsV2Table as Table,
)
from posthog.settings.data_stores import KAFKA_HOSTS, SESSION_RECORDING_KAFKA_HOSTS

table = Table()

existing_kafka_tables = [
    # 0041 added KAFKA_EVENTS_PLUGIN_INGESTION
    KafkaTable(KAFKA_HOSTS, KAFKA_EVENTS_PLUGIN_INGESTION),
    # 0042 added KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW (and KAFKA_SESSION_RECORDING_EVENTS, now unused)
    KafkaTable(KAFKA_HOSTS, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW),
]

new_kafka_tables = [
    KafkaTable(KAFKA_HOSTS, KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL),
    KafkaTable(SESSION_RECORDING_KAFKA_HOSTS, KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS),
    KafkaTable(SESSION_RECORDING_KAFKA_HOSTS, KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW),
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
