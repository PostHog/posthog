from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions("ALTER TABLE app_metrics RENAME COLUMN successes_on_retry TO skips"),
]
