from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.traces import KAFKA_TRACE_SPANS_AVRO_MV, KAFKA_TRACE_SPANS_AVRO_TABLE_SQL

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The Kafka engine table's column set is fixed at creation and the MV's SELECT changed, so both
# must be dropped and recreated. Neither is replicated (Kafka engine + MV), so no SYNC is needed.
# The recreated Kafka table adds `retention_days Nullable(Int32)` and
# `input_format_avro_allow_missing_fields = 1`; the MV now derives `original_expiry_timestamp` from
# the per-row `retention_days` when set, falling back to the batch `retention-days` header otherwise.
# Mirrors 0305, which did the same for logs.
#
# Both objects live on the logs nodes in every environment (see 0290 and the `coshared/apm_ingest`
# HCL layer), so unlike 0305 there is no prod/dev split to make here.
operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_trace_spans_avro_mv", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_trace_spans_avro", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_TRACE_SPANS_AVRO_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_TRACE_SPANS_AVRO_MV(), node_roles=[NodeRole.LOGS]),
]
