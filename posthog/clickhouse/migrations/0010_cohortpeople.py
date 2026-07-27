from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.cohorts.backend.models.sql import CREATE_COHORTPEOPLE_TABLE_SQL

operations = [run_sql_with_exceptions(CREATE_COHORTPEOPLE_TABLE_SQL())]
