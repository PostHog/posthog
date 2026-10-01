from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_DISTINCT_ID_USAGE, kafka_engine
from posthog.kafka_client.topics import KAFKA_DISTINCT_ID_USAGE_EVENTS_JSON

TABLE_BASE_NAME = "distinct_id_usage"
DATA_TABLE_NAME = f"sharded_{TABLE_BASE_NAME}"


def TRUNCATE_DISTINCT_ID_USAGE_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {DATA_TABLE_NAME}"


KAFKA_TABLE_NAME = f"kafka_{TABLE_BASE_NAME}"

# Kafka table - reads from the distinct_id_usage_events_json topic
# This topic is populated by a WarpStream pipeline that extracts only the fields we need
# We add settings to prevent poison pills from stopping ingestion
# kafka_skip_broken_messages is an int so we set it to skip all broken messages
KAFKA_DISTINCT_ID_USAGE_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC')
) ENGINE = {engine}
SETTINGS kafka_skip_broken_messages = 100
"""


def KAFKA_DISTINCT_ID_USAGE_TABLE_SQL():
    return KAFKA_DISTINCT_ID_USAGE_TABLE_BASE_SQL.format(
        table_name=KAFKA_TABLE_NAME,
        engine=kafka_engine(
            topic=KAFKA_DISTINCT_ID_USAGE_EVENTS_JSON,
            group=CONSUMER_GROUP_DISTINCT_ID_USAGE,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        ),
    )
