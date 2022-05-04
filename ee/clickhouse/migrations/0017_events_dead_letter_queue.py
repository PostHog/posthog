from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.dead_letter_queue import (
    DEAD_LETTER_QUEUE_TABLE_MV_SQL,
    DEAD_LETTER_QUEUE_TABLE_SQL,
    KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL,
)

operations = [
    migrations.RunSQL(DEAD_LETTER_QUEUE_TABLE_SQL()),
    migrations.RunSQL(KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL()),
    migrations.RunSQL(DEAD_LETTER_QUEUE_TABLE_MV_SQL),
]
