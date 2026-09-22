from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import KAFKA_LOGS34_AVRO_MV, KAFKA_LOGS_AVRO_TABLE_SQL, WRITABLE_LOGS34_TABLE_SQL
from posthog.run_mode import run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The Kafka engine table's column set is fixed at creation and the MV's SELECT changed, so both
# must be dropped and recreated. Neither is replicated (Kafka engine + MV), so no SYNC is needed.
# The recreated Kafka table adds `retention_days Nullable(Int32)` and
# `input_format_avro_allow_missing_fields = 1`; the MV now derives `original_expiry_timestamp` from
# the per-row `retention_days` when set, falling back to the batch `retention-days` header otherwise.
#
# The logs Kafka table + MV live on the ingestion-events nodes, so both are recreated there. Prod
# already hosts them there (moved manually) and drops from there; dev and local still have them on
# the logs nodes, so they drop from logs and recreate on ingestion-events, converging on prod.
# `run_mode()` is resolved here (not a raw CLOUD_DEPLOYMENT check) so a test re-import under a patched
# deployment picks up the right branch.
_drop_role = NodeRole.INGESTION_EVENTS if run_mode().is_prod_cloud else NodeRole.LOGS

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs34_avro_mv", node_roles=[_drop_role]),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs_avro", node_roles=[_drop_role]),
    # The MV writes into `writable_logs34` (Distributed → the logs cluster's `logs34`). It already
    # exists on prod's ingestion-events nodes; `IF NOT EXISTS` makes this a no-op there and creates it
    # on dev/local so the MV below has its destination.
    run_sql_with_exceptions(WRITABLE_LOGS34_TABLE_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
    run_sql_with_exceptions(KAFKA_LOGS_AVRO_TABLE_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
    run_sql_with_exceptions(KAFKA_LOGS34_AVRO_MV(to_table="writable_logs34"), node_roles=[NodeRole.INGESTION_EVENTS]),
]
