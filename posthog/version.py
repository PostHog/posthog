from posthog.constants import AnalyticsDBMS
from posthog.settings import PRIMARY_DB
from posthog.utils import print_warning

VERSION = "1.31.0"

if PRIMARY_DB == AnalyticsDBMS.POSTGRES:
    print_warning(
        [
            "Postgres as the primary database is no longer supported from PostHog 1.31.0 onwwards. Learn how to migrate here: https://posthog.com/docs/self-host/migrate-from-postgres-to-clickhouse"
        ]
    )
    exit(1)
