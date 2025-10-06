from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.behavioral_cohorts.sql import (
    BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE_SQL,
    DROP_BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(DROP_BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
]
