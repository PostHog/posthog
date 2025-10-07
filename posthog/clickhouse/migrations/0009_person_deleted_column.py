from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import KAFKA_PERSONS_TABLE_SQL, PERSONS_TABLE, PERSONS_TABLE_MV_SQL
<<<<<<< Updated upstream
=======
from django.conf import settings
>>>>>>> Stashed changes

operations = [
    run_sql_with_exceptions(f"DROP TABLE person_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE kafka_person ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(
        f"ALTER TABLE person ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' ADD COLUMN IF NOT EXISTS is_deleted Int8 DEFAULT 0"
    ),
    run_sql_with_exceptions(KAFKA_PERSONS_TABLE_SQL()),
    run_sql_with_exceptions(PERSONS_TABLE_MV_SQL(target_table=PERSONS_TABLE)),
]
