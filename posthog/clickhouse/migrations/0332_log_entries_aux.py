from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import (
    KAFKA_LOG_ENTRIES_AUX_TABLE_SQL,
    LOG_ENTRIES_AUX_DISTRIBUTED_TABLE_SQL,
    LOG_ENTRIES_AUX_MV_SQL,
    LOG_ENTRIES_AUX_WRITABLE_TABLE_SQL,
    LOG_ENTRIES_DATA_TABLE_SQL,
)
from posthog.run_mode import RunMode, run_mode

# Codifies the objects for the log_entries move to the aux cluster.
#
# All statements are IF NOT EXISTS and are a no-op on prod EU/US, where these objects were
# created by hand during the data migration and are already dual-writing. This migration makes
# dev/test and any future environment consistent with prod.
#
# `log_entries_data` (aux) is the S3-tiered go-forward store. `log_entries_distributed` is the
# reader over it, present on the aux and main clusters; the read cutover (swapping it with
# `log_entries`) is a separate follow-up migration. The Kafka consumer trio runs on
# ingestion-small in EU and ingestion-medium in US — role matching is exact, so the role is
# resolved per run mode; targeting both roles would start a second consumer set in each region.
# `run_mode()` is resolved here (not a raw CLOUD_DEPLOYMENT check) so a test re-import under a
# patched deployment picks up the right branch. Local single-node is unaffected either way:
# migration_tools collapses it to NodeRole.ALL.
_ingestion_role = NodeRole.INGESTION_MEDIUM if run_mode() is RunMode.CLOUD_US else NodeRole.INGESTION_SMALL

operations = [
    run_sql_with_exceptions(LOG_ENTRIES_DATA_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(LOG_ENTRIES_AUX_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.AUX, NodeRole.DATA]),
    run_sql_with_exceptions(LOG_ENTRIES_AUX_WRITABLE_TABLE_SQL(), node_roles=[_ingestion_role]),
    run_sql_with_exceptions(KAFKA_LOG_ENTRIES_AUX_TABLE_SQL(), node_roles=[_ingestion_role]),
    run_sql_with_exceptions(LOG_ENTRIES_AUX_MV_SQL(), node_roles=[_ingestion_role]),
]
