from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.dead_letter_queue import (
    DEAD_LETTER_QUEUE_TABLE_MV_SQL,
    DEAD_LETTER_QUEUE_TABLE_SQL,
    KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(DEAD_LETTER_QUEUE_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL()),
    run_sql_with_exceptions(DEAD_LETTER_QUEUE_TABLE_MV_SQL),
]
