from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Drop the WarpStream `calculated-events` Kafka engine table and MV for
# cohort_membership.
#
# `kafka_cohort_membership_ws` + `cohort_membership_ws_mv` were created by
# migration 0245 against the `warpstream_calculated_events` named collection.
# The `cohort_membership_changed` topic no longer has a producer, and the
# warpstream-calculated-events cluster is being decommissioned, so this pair is
# the last ClickHouse binding to it for cohort membership and has to go before
# the cluster is destroyed.
#
# Order: drop the MV first so it stops feeding `writable_cohort_membership`,
# then drop the Kafka engine table. `IF EXISTS` keeps the migration idempotent.
#
# CLOUD-ONLY: mirrors the guard on migration 0245, which only created these
# tables for US/EU/DEV. In non-cloud environments (CI, dev, hobby) they were
# never created.
#
# Node role: INGESTION_MEDIUM, matching where 0245 created them.

operations = (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS cohort_membership_ws_mv",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_cohort_membership_ws",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
    ]
)
