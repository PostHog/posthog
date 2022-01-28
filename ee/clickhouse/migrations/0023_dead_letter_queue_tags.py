from infi.clickhouse_orm import migrations

from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(
        f"ALTER TABLE events_dead_letter_queue ON CLUSTER {CLICKHOUSE_CLUSTER} ADD COLUMN IF NOT EXISTS tags Array(VARCHAR)"
    ),
]
