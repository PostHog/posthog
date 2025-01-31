from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import PERSON_STATIC_COHORT_TABLE_SQL

operations = [
    run_sql_with_exceptions(PERSON_STATIC_COHORT_TABLE_SQL()),
    run_sql_with_exceptions(PERSON_STATIC_COHORT_TABLE_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
]
