from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.performance.migrations import (
    DROP_KAFKA_PERFORMANCE_EVENTS_TABLE_SQL,
    DROP_PERFORMANCE_EVENTS_TABLE_MV_SQL,
    DROP_PERFORMANCE_EVENTS_TABLE_SQL,
    DROP_DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL,
    DROP_WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL,
)
from posthog.models.performance.sql import (
    KAFKA_PERFORMANCE_EVENTS_TABLE_SQL,
    PERFORMANCE_EVENTS_TABLE_MV_SQL,
    PERFORMANCE_EVENTS_TABLE_SQL,
    DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL,
    WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL,
)

operations = [
    # looking at past migrations we have to drop materialized views and kafka tables first
    run_sql_with_exceptions(DROP_PERFORMANCE_EVENTS_TABLE_MV_SQL()),
    run_sql_with_exceptions(DROP_KAFKA_PERFORMANCE_EVENTS_TABLE_SQL()),
    # drop the tables - they're all empty for sure
    run_sql_with_exceptions(DROP_WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(DROP_DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(DROP_PERFORMANCE_EVENTS_TABLE_SQL()),
    # recreate the tables - they've changed
    run_sql_with_exceptions(WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(PERFORMANCE_EVENTS_TABLE_SQL()),
    # and then recreate the materialized views and kafka tables
    run_sql_with_exceptions(KAFKA_PERFORMANCE_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(PERFORMANCE_EVENTS_TABLE_MV_SQL()),
]
