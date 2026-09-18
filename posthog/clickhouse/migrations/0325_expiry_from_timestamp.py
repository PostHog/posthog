from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import KAFKA_LOGS34_AVRO_MV
from posthog.clickhouse.traces import KAFKA_TRACE_SPANS_AVRO_MV

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# `original_expiry_timestamp` drives PARTITION BY and TTL on logs34 and trace_spans. The Kafka MVs
# derived it from `observed_timestamp` (ingest time), so a record with an old `timestamp` — late or
# backfilled data — stayed for the full retention window after ingest instead of after the moment it
# describes. Both MVs now derive it from `timestamp`.
#
# Only the MV SELECT changes; the Kafka engine tables keep their column set and stay in place. An MV
# is not replicated, so no SYNC is needed. Rows already stored keep their existing expiry.
#
# Placement follows the migrations that created these objects: the logs MV lives on the
# ingestion-events nodes since 0305/0307 and writes through `writable_logs34`; the traces MV lives
# on the logs nodes since 0290 and writes into `trace_spans` directly.

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs34_avro_mv", node_roles=[NodeRole.INGESTION_EVENTS]),
    run_sql_with_exceptions(KAFKA_LOGS34_AVRO_MV(to_table="writable_logs34"), node_roles=[NodeRole.INGESTION_EVENTS]),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_trace_spans_avro_mv", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_TRACE_SPANS_AVRO_MV(), node_roles=[NodeRole.LOGS]),
]
