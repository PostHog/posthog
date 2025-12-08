from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.cohortmembership.sql import (
    COHORT_MEMBERSHIP_MV_SQL,
    COHORT_MEMBERSHIP_TABLE_SQL,
    COHORT_MEMBERSHIP_WRITABLE_TABLE_SQL,
    KAFKA_COHORT_MEMBERSHIP_TABLE_SQL,
)
from posthog.models.precalculated_events.sql import (
    KAFKA_PRECALCULATED_EVENTS_TABLE_SQL,
    PRECALCULATED_EVENTS_DISTRIBUTED_TABLE_SQL,
    PRECALCULATED_EVENTS_MV_SQL,
    PRECALCULATED_EVENTS_SHARDED_TABLE_SQL,
    PRECALCULATED_EVENTS_WRITABLE_TABLE_SQL,
)

behavioral_cohorts_matches_table = "behavioral_cohorts_matches"

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {behavioral_cohorts_matches_table}", node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS writable_{behavioral_cohorts_matches_table}",
        node_roles=[NodeRole.DATA, NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS sharded_{behavioral_cohorts_matches_table}", node_roles=[NodeRole.DATA]
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS kafka_{behavioral_cohorts_matches_table}", node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {behavioral_cohorts_matches_table}_mv", node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(PRECALCULATED_EVENTS_SHARDED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(PRECALCULATED_EVENTS_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(KAFKA_PRECALCULATED_EVENTS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(PRECALCULATED_EVENTS_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(PRECALCULATED_EVENTS_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(COHORT_MEMBERSHIP_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(COHORT_MEMBERSHIP_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(KAFKA_COHORT_MEMBERSHIP_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(COHORT_MEMBERSHIP_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
]
