from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import EVENTS_TABLE_SQL
<<<<<<< Updated upstream
=======
from django.conf import settings
>>>>>>> Stashed changes

operations = [
    run_sql_with_exceptions(
        f"CREATE DATABASE IF NOT EXISTS {settings.CLICKHOUSE_DATABASE} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
    ),
    run_sql_with_exceptions(EVENTS_TABLE_SQL()),
]
