from infi.clickhouse_orm import migrations

from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(
        f"ALTER TABLE sharded_events ON CLUSTER '{CLICKHOUSE_CLUSTER}' MODIFY COLUMN properties VARCHAR CODEC(ZSTD(3))"
    ),
]
