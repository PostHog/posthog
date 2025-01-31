from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.cohort.sql import CREATE_COHORTPEOPLE_TABLE_SQL

operations = [
    run_sql_with_exceptions(CREATE_COHORTPEOPLE_TABLE_SQL()),
    run_sql_with_exceptions(CREATE_COHORTPEOPLE_TABLE_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
]
