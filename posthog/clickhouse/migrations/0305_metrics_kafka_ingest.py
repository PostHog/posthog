from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    KAFKA_METRICS_AVRO_MV,
    KAFKA_METRICS_AVRO_TABLE_SQL,
    KAFKA_METRICS_AVRO_TO_KAFKA_METRICS_MV,
    KAFKA_METRICS_AVRO_TO_METRIC_SAMPLES_MV,
    KAFKA_METRICS_AVRO_TO_METRIC_SERIES_MV,
    METRICS1_TABLE_SQL,
    METRICS_DISTRIBUTED_TABLE_SQL,
    METRICS_KAFKA_METRICS_TABLE_SQL,
)

# `metrics1` (raw) is the destination of kafka_metrics_avro_mv, but no earlier migration
# creates it: on cloud it is provisioned out of band, and on a dev laptop through the
# schema-sync path — neither runs in a migrations-only environment. 0283 created
# metric_samples1/metric_series1 the same way but left metrics1 out. Create it and its
# distributed reader here, before the view, so the overlay ingest works wherever
# migrations run. All statements are IF NOT EXISTS, so this is a no-op where the tables
# already exist.
operations = [
    run_sql_with_exceptions(METRICS1_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS_KAFKA_METRICS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO_TO_METRIC_SAMPLES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO_TO_METRIC_SERIES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO_TO_KAFKA_METRICS_MV(), node_roles=[NodeRole.LOGS]),
]
