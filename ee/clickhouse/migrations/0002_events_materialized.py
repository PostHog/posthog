from infi.clickhouse_orm import migrations  # type: ignore

from ee.clickhouse.sql.events import (
    EVENTS_COLLAPSING_VIEW,
    EVENTS_WITH_PROPS_TABLE_SQL,
    MAT_EVENT_PROP_TABLE_SQL,
    MAT_EVENTS_WITH_PROPS_TABLE_SQL,
)

operations = [
    migrations.RunSQL(EVENTS_COLLAPSING_VIEW),
    migrations.RunSQL(EVENTS_WITH_PROPS_TABLE_SQL),
    migrations.RunSQL(MAT_EVENTS_WITH_PROPS_TABLE_SQL),
    migrations.RunSQL(MAT_EVENT_PROP_TABLE_SQL),
]
