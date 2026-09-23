from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.traces import KAFKA_TRACE_SPANS_AVRO_MV, KAFKA_TRACE_SPANS_AVRO_TABLE_SQL
from posthog.run_mode import RunMode, run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The Kafka engine table's column set is fixed at creation and the MV's SELECT changed, so both
# must be dropped and recreated. Neither is replicated (Kafka engine + MV), so no SYNC is needed.
# The recreated Kafka table adds `retention_days Nullable(Int32)` and
# `input_format_avro_allow_missing_fields = 1`; the MV now derives `original_expiry_timestamp` from
# the per-row `retention_days` when set, falling back to the batch `retention-days` header otherwise.
# Mirrors 0305, which did the same for logs.
#
# Which role hosts the pair differs by environment: the `coshared/apm_ingest` HCL layer that holds
# them is composed by the apm role on dev, and by the logs role on prod-us, prod-eu and local-multi.
# Role matching is exact, so targeting logs everywhere would leave dev's live pair untouched and
# create a second, unfed one on its logs nodes. `run_mode()` is resolved here (not a raw
# CLOUD_DEPLOYMENT check) so a test re-import under a patched deployment picks up the right branch.
# Local single-node is unaffected either way: migration_tools collapses it to NodeRole.ALL.
_role = NodeRole.APM if run_mode() is RunMode.CLOUD_DEV else NodeRole.LOGS

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_trace_spans_avro_mv", node_roles=[_role]),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_trace_spans_avro", node_roles=[_role]),
    run_sql_with_exceptions(KAFKA_TRACE_SPANS_AVRO_TABLE_SQL(), node_roles=[_role]),
    run_sql_with_exceptions(KAFKA_TRACE_SPANS_AVRO_MV(), node_roles=[_role]),
]
