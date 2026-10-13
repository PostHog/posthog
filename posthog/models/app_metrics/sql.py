from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_APP_METRICS, kafka_engine
from posthog.kafka_client.topics import KAFKA_APP_METRICS

APP_METRICS_TABLE = "app_metrics"

KAFKA_APP_METRICS_TABLE = f"kafka_{APP_METRICS_TABLE}"

KAFKA_APP_METRICS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {KAFKA_APP_METRICS_TABLE}
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    plugin_config_id Int64,
    category LowCardinality(String),
    job_id String,
    successes Int64,
    successes_on_retry Int64,
    failures Int64,
    error_uuid UUID,
    error_type String,
    error_details String CODEC(ZSTD(3))
)
ENGINE={kafka_engine(topic=KAFKA_APP_METRICS, group=CONSUMER_GROUP_APP_METRICS)}
"""
)
