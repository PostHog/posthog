from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.web_vitals.sql import (
    NETWORK_VITALS_TABLE_MV_SQL,
    KAFKA_NETWORK_VITALS_TABLE_SQL,
    DISTRIBUTED_NETWORK_VITALS_TABLE_SQL,
    WRITABLE_NETWORK_VITALS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(WRITABLE_NETWORK_VITALS_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_NETWORK_VITALS_TABLE_SQL()),
    run_sql_with_exceptions(NETWORK_VITALS_TABLE_MV_SQL()),
    run_sql_with_exceptions(KAFKA_NETWORK_VITALS_TABLE_SQL()),
    run_sql_with_exceptions(NETWORK_VITALS_TABLE_MV_SQL()),
]
