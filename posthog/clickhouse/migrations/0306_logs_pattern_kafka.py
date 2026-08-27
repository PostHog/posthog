from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import KAFKA_LOGS34_AVRO_MV, KAFKA_LOGS_AVRO_TABLE_SQL
from posthog.run_mode import run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# Reads the masked `pattern` and `pattern_version` the Node consumer stamps onto each log record
# into the matching logs34 columns. Until this runs, the producer writes both fields and nothing
# reads them, so every logs34 row keeps `pattern = ''` and `pattern_version = 0`.
#
# A Kafka engine table's column set is fixed at creation, so the two new fields cannot be added by
# ALTER — the table and the MV that reads it are dropped and recreated, as in the migration that
# added `retention_days`. Neither is replicated (Kafka engine + MV), so no SYNC is needed.
#
# The MV coalesces both fields. A record written before the consumer stamped it carries null, which
# must land as `''` and version 0 — the sentinel that marks a row as predating masking. The Kafka
# table already sets `input_format_avro_allow_missing_fields = 1`, so a message whose writer schema
# lacks the fields entirely reads as null rather than failing the batch.
#
# Placement follows the same rule as the retention_days migration: prod hosts these on the
# ingestion-events nodes and drops from there, while dev and local still have them on the logs
# nodes. `run_mode()` is resolved here so a test re-import under a patched deployment picks up the
# right branch.
_drop_role = NodeRole.INGESTION_EVENTS if run_mode().is_prod_cloud else NodeRole.LOGS

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs34_avro_mv", node_roles=[_drop_role]),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs_avro", node_roles=[_drop_role]),
    run_sql_with_exceptions(KAFKA_LOGS_AVRO_TABLE_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
    run_sql_with_exceptions(KAFKA_LOGS34_AVRO_MV(to_table="writable_logs34"), node_roles=[NodeRole.INGESTION_EVENTS]),
]
