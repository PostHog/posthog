from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.web_vitals.sql import (
    WEB_VITALS_TABLE_MV_SQL,
    KAFKA_WEB_VITALS_TABLE_SQL,
    WEB_VITALS_TABLE_SQL,
    DISTRIBUTED_WEB_VITALS_TABLE_SQL,
    WRITABLE_WEB_VITALS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(WRITABLE_WEB_VITALS_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_WEB_VITALS_TABLE_SQL()),
    run_sql_with_exceptions(WEB_VITALS_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_WEB_VITALS_TABLE_SQL()),
    run_sql_with_exceptions(WEB_VITALS_TABLE_MV_SQL()),
]
