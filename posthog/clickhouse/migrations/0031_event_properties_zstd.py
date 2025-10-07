from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
<<<<<<< Updated upstream
=======
from django.conf import settings
>>>>>>> Stashed changes

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE sharded_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' MODIFY COLUMN properties VARCHAR CODEC(ZSTD(3))"
    )
]
