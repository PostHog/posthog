from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [run_sql_with_exceptions("SELECT 1")]
