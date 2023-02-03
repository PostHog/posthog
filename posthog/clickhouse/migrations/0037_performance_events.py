from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.performance.sql import (
    DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL,
    KAFKA_PERFORMANCE_EVENTS_TABLE_SQL,
    PERFORMANCE_EVENTS_TABLE_MV_SQL,
    PERFORMANCE_EVENTS_TABLE_SQL,
    WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(PERFORMANCE_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_PERFORMANCE_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(PERFORMANCE_EVENTS_TABLE_MV_SQL()),
]
