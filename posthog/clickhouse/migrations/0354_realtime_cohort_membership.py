from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.cohorts.backend.facade.clickhouse import (
    KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL,
    REALTIME_COHORT_MEMBERSHIP_MV_SQL,
    REALTIME_COHORT_MEMBERSHIP_TABLE_SQL,
    WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL,
)

# The storage table sits on DATA next to cohortpeople, because audience queries join it with persons there.
operations = [
    run_sql_with_exceptions(REALTIME_COHORT_MEMBERSHIP_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(REALTIME_COHORT_MEMBERSHIP_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
]
