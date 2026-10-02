from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_PRECALCULATED_EVENTS, kafka_engine

PRECALCULATED_EVENTS_TABLE = "precalculated_events"

PRECALCULATED_EVENTS_KAFKA_TABLE = f"kafka_{PRECALCULATED_EVENTS_TABLE}"


def KAFKA_PRECALCULATED_EVENTS_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    date Nullable(Date),
    distinct_id String,
    person_id UUID,
    condition String,
    uuid UUID,
    source String
) ENGINE = {engine}
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1
""".format(
        table_name=PRECALCULATED_EVENTS_KAFKA_TABLE,
        engine=kafka_engine(topic="clickhouse_prefiltered_events", group=CONSUMER_GROUP_PRECALCULATED_EVENTS),
    )
