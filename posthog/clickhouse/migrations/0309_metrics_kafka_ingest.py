from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    KAFKA_METRICS_AVRO_MV,
    KAFKA_METRICS_AVRO_TABLE_SQL,
    KAFKA_METRICS_AVRO_TO_KAFKA_METRICS_MV,
    KAFKA_METRICS_AVRO_TO_METRIC_SAMPLES_MV,
    KAFKA_METRICS_AVRO_TO_METRIC_SERIES_MV,
    METRIC_ATTRIBUTES_MV,
    METRIC_ATTRIBUTES_TABLE_SQL,
    METRIC_RESOURCE_ATTRIBUTES_MV,
    METRICS1_TABLE_SQL,
    METRICS_DISTRIBUTED_TABLE_SQL,
    METRICS_KAFKA_METRICS_TABLE_SQL,
)

# This migration replaces the hand-run bin/clickhouse-metrics.sql init script (deleted in
# the same change) — metrics was the last product provisioning its ClickHouse objects
# that way; logs and traces already moved to migrations.
#
# None of these objects had a creating migration: on cloud they are provisioned out of
# band (the HCL logs-cluster layer), and on a dev laptop through the init script or the
# schema-sync path — none of which runs in a migrations-only environment. 0283 created
# metric_samples1/metric_series1 but left out metrics1 (the kafka_metrics_avro_mv
# destination), metric_attributes and its two feeder views, and the whole Kafka ingest
# chain. Create them here, storage tables before the views that write to them. All
# statements are IF NOT EXISTS, so this is a no-op where the objects already exist.
operations = [
    run_sql_with_exceptions(METRICS1_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRIC_ATTRIBUTES_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRIC_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRIC_RESOURCE_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS_KAFKA_METRICS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO_TO_METRIC_SAMPLES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO_TO_METRIC_SERIES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO_TO_KAFKA_METRICS_MV(), node_roles=[NodeRole.LOGS]),
]
