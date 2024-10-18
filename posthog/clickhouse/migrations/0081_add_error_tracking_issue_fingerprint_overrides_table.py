from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.error_tracking.sql import ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL

operations = [
    run_sql_with_exceptions(ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL()),
]
