from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.events import EVENTS_WITH_DENORMALIZED_PROPS, EVENTS_WITH_DENORMALIZED_PROPS_MV

operations = [
    migrations.RunSQL(EVENTS_WITH_DENORMALIZED_PROPS),
    migrations.RunSQL(EVENTS_WITH_DENORMALIZED_PROPS_MV),
]
