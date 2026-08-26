from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import KAFKA_LOGS34_AVRO_MV, KAFKA_LOGS_AVRO_TABLE_SQL

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The Kafka engine table's column set is fixed at creation and the MV's SELECT changed, so both
# must be dropped and recreated. Neither is replicated (Kafka engine + MV), so no SYNC is needed.
# The recreated Kafka table adds `retention_days Nullable(Int32)` and
# `input_format_avro_allow_missing_fields = 1`; the MV now derives `original_expiry_timestamp` from
# the per-row `retention_days` when set, falling back to the batch `retention-days` header otherwise.
operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs34_avro_mv", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs_avro", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_LOGS_AVRO_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_LOGS34_AVRO_MV(), node_roles=[NodeRole.LOGS]),
]
