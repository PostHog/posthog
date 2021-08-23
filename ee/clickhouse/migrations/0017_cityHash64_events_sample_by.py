from infi.clickhouse_orm import migrations

from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(f"ALTER TABLE events ON CLUSTER {CLICKHOUSE_CLUSTER} MODIFY SAMPLE BY cityHash64(uuid)"),
]
