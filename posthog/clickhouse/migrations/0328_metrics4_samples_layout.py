from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    METRICS4_INPUT_TO_METRICS4_SAMPLES_MV,
    METRICS4_SAMPLES_TABLE_SQL,
    WRITABLE_METRICS4_SAMPLES_TABLE_SQL,
)
from posthog.clickhouse.metrics.metrics4 import (
    METRICS4_INPUT_TABLE_NAME,
    METRICS4_SAMPLES_TABLE_NAME,
    WRITABLE_METRICS4_SAMPLES_TABLE_NAME,
)

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The new row layout drops `observed_timestamp_arr`, adds a scalar
# `observed_timestamp`, and raises the index granularity. None of the three is
# expressible as an ALTER, so the samples chain is recreated.
#
# This DISCARDS the current `metrics4_samples` contents. No product surface reads
# metrics4 -- the HogQL tables still point at the metrics2 chain -- so the table
# holds a backfill only. Ingestion refills it from the same Kafka topic.
operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.{METRICS4_INPUT_TABLE_NAME}_to_{METRICS4_SAMPLES_TABLE_NAME} SYNC",
        node_roles=[NodeRole.APM],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.{WRITABLE_METRICS4_SAMPLES_TABLE_NAME} SYNC",
        node_roles=[NodeRole.APM],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.{METRICS4_SAMPLES_TABLE_NAME} SYNC",
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(METRICS4_SAMPLES_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(WRITABLE_METRICS4_SAMPLES_TABLE_SQL(), node_roles=[NodeRole.APM]),
    run_sql_with_exceptions(METRICS4_INPUT_TO_METRICS4_SAMPLES_MV(), node_roles=[NodeRole.APM]),
]
