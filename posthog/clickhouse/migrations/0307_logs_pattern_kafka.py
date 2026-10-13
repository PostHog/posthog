from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import KAFKA_LOGS34_AVRO_MV, KAFKA_LOGS_AVRO_TABLE_SQL

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# Reads the masked `pattern` and `pattern_version` the Node consumer stamps onto each log record
# into the matching logs34 columns. Until this runs, the producer writes both fields and nothing
# reads them, so every logs34 row keeps `pattern = ''` and `pattern_version = 0`.
#
# A Kafka engine table's column set is fixed at creation, so the two new fields cannot be added by
# ALTER — the table and the MV that reads it are dropped and recreated, as in the migration that
# added `retention_days`. Neither is replicated (Kafka engine + MV), so no SYNC is needed.
#
# `writable_logs34` needs the columns too. It spells its column list out rather than deriving it
# from `logs34`, so the migration that added the columns to `logs34` left it behind, and an MV
# selecting `pattern` into it fails with "column not found in the target table". ALTER rather than
# recreate: it is a Distributed table, so adding a column is metadata-only, while dropping it would
# break writes still in flight. The ALTER runs before the MV so the target is ready.
#
# The MV coalesces both fields. A record written before the consumer stamped it carries null, which
# must land as `''` and version 0 — the sentinel that marks a row as predating masking. The Kafka
# table already sets `input_format_avro_allow_missing_fields = 1`, so a message whose writer schema
# lacks the fields entirely reads as null rather than failing the batch.
#
# Everything here targets the ingestion-events nodes, with no per-deployment branch. The
# retention_days migration branched because it performed the move: prod already hosted these
# objects on ingestion-events, while dev and local still had them on the logs nodes, so it dropped
# from wherever each environment kept them. Its creates were unconditional, so every environment
# converges on ingestion-events once it runs. A later migration that still branched would drop from
# an empty logs cluster, and `CREATE ... IF NOT EXISTS` would then leave the old Kafka table and MV
# in place — the change would apply nowhere while reporting success.

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs34_avro_mv", node_roles=[NodeRole.INGESTION_EVENTS]),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs_avro", node_roles=[NodeRole.INGESTION_EVENTS]),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.writable_logs34 "
        "ADD COLUMN IF NOT EXISTS pattern String, "
        "ADD COLUMN IF NOT EXISTS pattern_version UInt8",
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(KAFKA_LOGS_AVRO_TABLE_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
    run_sql_with_exceptions(KAFKA_LOGS34_AVRO_MV(to_table="writable_logs34"), node_roles=[NodeRole.INGESTION_EVENTS]),
]
