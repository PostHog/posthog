from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_PRECALCULATED_PERSON_PROPERTIES, kafka_engine

PRECALCULATED_PERSON_PROPERTIES_TABLE = "precalculated_person_properties"

PRECALCULATED_PERSON_PROPERTIES_KAFKA_TABLE = f"kafka_{PRECALCULATED_PERSON_PROPERTIES_TABLE}"


def KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    distinct_id String,
    person_id UUID,
    condition String,
    matches Bool,
    source String
) ENGINE = {engine}
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1
""".format(
        table_name=PRECALCULATED_PERSON_PROPERTIES_KAFKA_TABLE,
        engine=kafka_engine(
            topic="clickhouse_precalculated_person_properties", group=CONSUMER_GROUP_PRECALCULATED_PERSON_PROPERTIES
        ),
    )
