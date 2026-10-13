from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_PROPERTY_VALUES, kafka_engine, kafka_num_consumers
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_PROPERTY_VALUES

TABLE_NAME = "property_values"

KAFKA_TABLE_NAME = f"kafka_{TABLE_NAME}"

# The Kafka message schema: pre-processed rows from the property-values aggregator.
# Each message is one (team_id, property_type, property_key, property_value)
# tuple plus an accumulated `property_count` from the aggregator's flush window.
KAFKA_PROPERTY_VALUES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    `team_id` Int64,
    `property_type` LowCardinality(String),
    `property_key` String,
    `property_value` String,
    `property_count` UInt64
) ENGINE = {engine}
SETTINGS kafka_num_consumers = {num_consumers}, kafka_thread_per_consumer = 1
"""


def KAFKA_PROPERTY_VALUES_TABLE_SQL_FN() -> str:
    return KAFKA_PROPERTY_VALUES_TABLE_SQL.format(
        table_name=KAFKA_TABLE_NAME,
        num_consumers=kafka_num_consumers(8),
        engine=kafka_engine(
            topic=KAFKA_CLICKHOUSE_PROPERTY_VALUES,
            group=CONSUMER_GROUP_PROPERTY_VALUES,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        ),
    )
