from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.group.sql import GROUPS_TABLE, GROUPS_TABLE_MV_SQL, GROUPS_TABLE_SQL, KAFKA_GROUPS_TABLE_SQL

operations = [
    run_sql_with_exceptions(GROUPS_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_GROUPS_TABLE_SQL()),
    run_sql_with_exceptions(GROUPS_TABLE_MV_SQL(target_table=GROUPS_TABLE)),
]
