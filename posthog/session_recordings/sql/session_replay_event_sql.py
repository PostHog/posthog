from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_SESSION_REPLAY_EVENTS, kafka_engine
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS


def SESSION_REPLAY_EVENTS_DATA_TABLE():
    return "sharded_session_replay_events"


def TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SESSION_REPLAY_EVENTS_DATA_TABLE()}"


KAFKA_SESSION_REPLAY_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    first_timestamp DateTime64(6, 'UTC'),
    last_timestamp DateTime64(6, 'UTC'),
    block_url Nullable(String),
    first_url Nullable(VARCHAR),
    urls Array(String),
    click_count Int64,
    keypress_count Int64,
    mouse_activity_count Int64,
    active_milliseconds Int64,
    console_log_count Int64,
    console_warn_count Int64,
    console_error_count Int64,
    size Int64,
    event_count Int64,
    message_count Int64,
    snapshot_source LowCardinality(Nullable(String)),
    snapshot_library Nullable(String),
    snapshot_mode LowCardinality(Nullable(String)),
    retention_period_days Nullable(Int64),
    is_deleted UInt8,
    ai_tags_fixed Array(String),
    ai_tags_freeform Array(String),
    ai_highlighted UInt8,
    surfacing_score Nullable(Float32),
) ENGINE = {engine}
"""


def KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=True):
    return KAFKA_SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.format(
        table_name="kafka_session_replay_events",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS, group=CONSUMER_GROUP_SESSION_REPLAY_EVENTS),
    )
