from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import KAFKA_LOGS34_AVRO_MV, KAFKA_LOGS_AVRO_KAFKA_METRICS_MV_SELECT

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# Records the logs_ingestion partition of each log row, so the live logs checkpoint can track
# progress for both topics that a row passes through. The Node consumer sends the partition in the
# `source_topic` and `source_partition` headers.
#
# The columns go on every table that the row passes through, before the MVs that write or read
# them. Adding a column to a Distributed table changes only its metadata.
#
# The Kafka MV gets new output columns, so it is dropped and created again. The Kafka table stays,
# with the same consumer group, so the gap causes lag and no data loss. The metrics MV keeps the
# same output columns, so MODIFY QUERY is sufficient.

ADD_COLUMNS = "ADD COLUMN IF NOT EXISTS _source_topic String, ADD COLUMN IF NOT EXISTS _source_partition UInt32"

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs34 {ADD_COLUMNS}",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs_distributed {ADD_COLUMNS}",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.writable_logs34 {ADD_COLUMNS}",
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.kafka_logs_avro_kafka_metrics_mv MODIFY QUERY\n{KAFKA_LOGS_AVRO_KAFKA_METRICS_MV_SELECT()}",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs34_avro_mv", node_roles=[NodeRole.INGESTION_EVENTS]),
    run_sql_with_exceptions(KAFKA_LOGS34_AVRO_MV(to_table="writable_logs34"), node_roles=[NodeRole.INGESTION_EVENTS]),
]
