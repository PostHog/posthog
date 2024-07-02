from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON
from posthog.models.kafka_debug.sql import (
    KafkaDebugKafkaTable,
)
from posthog.settings.data_stores import KAFKA_HOSTS


kafka_table = KafkaDebugKafkaTable(brokers=KAFKA_HOSTS, topic=KAFKA_EVENTS_JSON)


operations = [
    # We just need to drop and recreate the kafka table here to
    # correct the serialization type (LineAsString from JSONEachRow)
    run_sql_with_exceptions(kafka_table.get_drop_table_sql()),
    run_sql_with_exceptions(kafka_table.get_create_table_sql()),
]
