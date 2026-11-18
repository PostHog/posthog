from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    KAFKA_METRICS_AVRO4_MV,
    METRICS4_INPUT_TO_METRICS_KAFKA_METRICS_MV,
    WRITABLE_METRICS_KAFKA_METRICS_TABLE_SQL,
)

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# metrics_kafka_metrics already exists on the logs cluster: 0309 created it, and 0340 dropped the
# only view that wrote to it. The new view counts each row toward both Kafka partitions it passed
# through. The Node consumer sends the ingestion-metrics partition in the `source_topic` and
# `source_partition` headers.
#
# The source columns go on metrics4_input before the views that read or write them, and the
# writable table goes before the view that inserts into it. The Kafka view gets new output columns,
# so it is dropped and created again. The Kafka table stays, with the same consumer group, so the
# gap causes lag and no data loss.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_input ADD COLUMN IF NOT EXISTS _source_topic String, "
        "ADD COLUMN IF NOT EXISTS _source_partition UInt32",
        node_roles=[NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(WRITABLE_METRICS_KAFKA_METRICS_TABLE_SQL(), node_roles=[NodeRole.APM]),
    run_sql_with_exceptions(METRICS4_INPUT_TO_METRICS_KAFKA_METRICS_MV(), node_roles=[NodeRole.APM]),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_metrics_avro4_mv", node_roles=[NodeRole.APM]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO4_MV(), node_roles=[NodeRole.APM]),
]
