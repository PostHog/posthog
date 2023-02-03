from posthog.clickhouse.dead_letter_queue import DEAD_LETTER_QUEUE_TABLE_MV_SQL, KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    run_sql_with_exceptions(f"DROP TABLE events_dead_letter_queue_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE kafka_events_dead_letter_queue ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(
        f"ALTER TABLE events_dead_letter_queue ON CLUSTER '{CLICKHOUSE_CLUSTER}' ADD COLUMN IF NOT EXISTS tags Array(VARCHAR) AFTER error"
    ),
    run_sql_with_exceptions(KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL()),
    run_sql_with_exceptions(DEAD_LETTER_QUEUE_TABLE_MV_SQL),
]
