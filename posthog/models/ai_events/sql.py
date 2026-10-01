from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_AI_EVENTS, kafka_engine
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_AI_EVENTS_JSON

TABLE_BASE_NAME = "ai_events"

KAFKA_TABLE_NAME = f"kafka_{TABLE_BASE_NAME}_json"

# Kafka engine table — receives the standard RawKafkaEvent JSON format
KAFKA_AI_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_properties VARCHAR,
    person_created_at DateTime64,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)
) ENGINE = {engine}
"""


def KAFKA_AI_EVENTS_TABLE_SQL():
    return KAFKA_AI_EVENTS_TABLE_BASE_SQL.format(
        table_name=KAFKA_TABLE_NAME,
        engine=kafka_engine(topic=KAFKA_CLICKHOUSE_AI_EVENTS_JSON, group=CONSUMER_GROUP_AI_EVENTS),
    )
