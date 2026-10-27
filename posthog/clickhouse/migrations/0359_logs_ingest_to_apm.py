from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import KAFKA_LOGS34_AVRO_MV, KAFKA_LOGS_AVRO_TABLE_SQL, WRITABLE_LOGS34_TABLE_SQL
from posthog.run_mode import run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The cloud envs run the logs Kafka ingest on the ingestion-apm nodes, as the HCL `apm` role composes
# `coshared/logs_avro_ingest` for dev, prod-us and prod-eu. 0305, 0307 and 0348 put it on the
# ingestion-events nodes in prod, so a cluster built from the migration history would consume there.
# On a cluster that already runs the ingest on apm, every statement is a no-op.
#
# The apm side is created first. Both sides use the same `kafka_group_name`, so the apm consumers
# join the group and take partitions before the ingestion-events consumers leave, and the topic always
# has a consumer. The ingestion-events Kafka table drops before its MV so that its consumers leave the
# group at once. With the MV dropped first, they would keep their partitions and consume nothing.
# The apm creates require hosts, so that a topology with no apm hosts fails the migration before the
# drops instead of leaving no consumer.
#
# The ingestion-events `writable_logs34` stays. A dropped Distributed table loses the blocks it still
# queues for the logs cluster, and no migration statement can drain it only where it exists. With the
# MV gone nothing writes to it, so it only sends what it already holds. Drop it by hand once
# `system.distribution_queue` shows it empty.
#
# The multinode stack keeps the ingest on its ingestion-events node, so this migration is cloud-only.
operations = (
    [
        run_sql_with_exceptions(WRITABLE_LOGS34_TABLE_SQL(), node_roles=[NodeRole.APM], require_hosts=True),
        run_sql_with_exceptions(KAFKA_LOGS_AVRO_TABLE_SQL(), node_roles=[NodeRole.APM], require_hosts=True),
        run_sql_with_exceptions(
            KAFKA_LOGS34_AVRO_MV(to_table="writable_logs34"), node_roles=[NodeRole.APM], require_hosts=True
        ),
        run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs_avro", node_roles=[NodeRole.INGESTION_EVENTS]),
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {DB}.kafka_logs34_avro_mv", node_roles=[NodeRole.INGESTION_EVENTS]
        ),
    ]
    if run_mode().is_deployed_cloud
    else []
)
