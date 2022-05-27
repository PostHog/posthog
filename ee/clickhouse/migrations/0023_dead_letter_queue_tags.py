from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.dead_letter_queue import DEAD_LETTER_QUEUE_TABLE_MV_SQL, KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(f"DROP TABLE events_dead_letter_queue_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE kafka_events_dead_letter_queue ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(
        f"ALTER TABLE events_dead_letter_queue ON CLUSTER '{CLICKHOUSE_CLUSTER}' ADD COLUMN IF NOT EXISTS tags Array(VARCHAR) AFTER error"
    ),
    migrations.RunSQL(KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL()),
    migrations.RunSQL(DEAD_LETTER_QUEUE_TABLE_MV_SQL),
]
