from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.cohortmembership.sql import COHORT_MEMBERSHIP_WS_MV_SQL, KAFKA_COHORT_MEMBERSHIP_WS_TABLE_SQL

# Migration to create a WarpStream Kafka engine table for cohort_membership_changed.
#
# Coexists alongside the existing MSK Kafka engine table, reading from the same
# cohort_membership_changed topic but via the warpstream_calculated_events named
# collection with its own consumer group to avoid conflicts with the MSK table.
#
# CLOUD-ONLY: In non-cloud environments (CI, dev, hobby) there is only one ClickHouse
# node, so both the MSK and WS materialized views would consume the same Kafka topic
# and write to the same target table, doubling every cohort_membership row.
#
# New tables (INGESTION_MEDIUM, matching existing MSK table from migration 0175):
# - kafka_cohort_membership_ws + cohort_membership_ws_mv

operations = (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [
        run_sql_with_exceptions(
            KAFKA_COHORT_MEMBERSHIP_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            COHORT_MEMBERSHIP_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
    ]
)
