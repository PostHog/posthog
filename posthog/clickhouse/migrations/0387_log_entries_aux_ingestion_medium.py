from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import (
    KAFKA_LOG_ENTRIES_AUX_TABLE,
    KAFKA_LOG_ENTRIES_AUX_TABLE_SQL,
    LOG_ENTRIES_AUX_MV,
    LOG_ENTRIES_AUX_MV_SQL,
    LOG_ENTRIES_AUX_WRITABLE_TABLE_SQL,
)
from posthog.run_mode import run_mode
from posthog.settings import CLICKHOUSE_DATABASE

# The cloud deployments run the aux log_entries Kafka consumer trio on the ingestion-medium nodes.
# 0332 resolves the role per run mode and puts the trio on ingestion-small in some of them, so a
# cluster built from the migration history would consume there. On a cluster that already runs the
# trio on ingestion-medium, every statement is a no-op.
#
# The ingestion-medium side is created first. Both sides use the same `kafka_group_name`, so the new
# consumers join the group and take partitions before the ingestion-small consumers leave, and the
# topic always has a consumer. The ingestion-small Kafka table drops before its MV, which makes its
# consumers leave the group at once. The creates require hosts, so that a topology with no
# ingestion-medium hosts fails the migration before the drops instead of leaving no consumer.
#
# The ingestion-small `writable_log_entries_aux` stays. A dropped Distributed table loses the blocks
# it still queues for the aux cluster, and no migration statement can drain it only where it exists.
# With the MV gone nothing writes to it. Drop it by hand once `system.distribution_queue` shows it
# empty.
#
# The multinode stack keeps the trio on its ingestion-small node, so this migration is cloud-only.
operations = (
    [
        run_sql_with_exceptions(
            LOG_ENTRIES_AUX_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM], require_hosts=True
        ),
        run_sql_with_exceptions(
            KAFKA_LOG_ENTRIES_AUX_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM], require_hosts=True
        ),
        run_sql_with_exceptions(LOG_ENTRIES_AUX_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM], require_hosts=True),
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {CLICKHOUSE_DATABASE}.{KAFKA_LOG_ENTRIES_AUX_TABLE}",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {CLICKHOUSE_DATABASE}.{LOG_ENTRIES_AUX_MV}", node_roles=[NodeRole.INGESTION_SMALL]
        ),
    ]
    if run_mode().is_deployed_cloud
    else []
)
