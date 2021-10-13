from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.events import EVENTS_TABLE, EVENTS_TABLE_MV_SQL, KAFKA_EVENTS_TABLE_SQL
from ee.clickhouse.sql.groups import GROUPS_TABLE_MV_SQL, GROUPS_TABLE_SQL, KAFKA_GROUPS_TABLE_SQL
from posthog.constants import GROUP_TYPES_LIMIT
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_REPLICATION

operations = [
    migrations.RunSQL(GROUPS_TABLE_SQL),
    migrations.RunSQL(KAFKA_GROUPS_TABLE_SQL),
    migrations.RunSQL(GROUPS_TABLE_MV_SQL),
]

if CLICKHOUSE_REPLICATION:
    raise NotImplementedError("Can't handle replication yet")

operations.extend(
    [
        migrations.RunSQL(f"DROP TABLE events_mv ON CLUSTER {CLICKHOUSE_CLUSTER}"),
        migrations.RunSQL(f"DROP TABLE kafka_events ON CLUSTER {CLICKHOUSE_CLUSTER}"),
    ]
)

operations.extend(
    migrations.RunSQL(
        f"ALTER TABLE {EVENTS_TABLE} ON CLUSTER {CLICKHOUSE_CLUSTER} ADD COLUMN IF NOT EXISTS group_{index} VARCHAR"
    )
    for index in range(GROUP_TYPES_LIMIT)
)

operations.extend([migrations.RunSQL(KAFKA_EVENTS_TABLE_SQL), migrations.RunSQL(EVENTS_TABLE_MV_SQL)])
