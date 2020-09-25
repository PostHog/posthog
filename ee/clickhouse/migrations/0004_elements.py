from infi.clickhouse_orm import migrations  # type: ignore

from ee.clickhouse.sql.elements import (
    ELEMENTS_PROPERTIES_MAT,
    ELEMENTS_TABLE_SQL,
    ELEMENTS_WITH_ARRAY_PROPS,
    ELEMENTS_WITH_ARRAY_PROPS_MAT,
)

operations = [
    migrations.RunSQL(ELEMENTS_TABLE_SQL),
    migrations.RunSQL(ELEMENTS_WITH_ARRAY_PROPS),
    migrations.RunSQL(ELEMENTS_WITH_ARRAY_PROPS_MAT),
    migrations.RunSQL(ELEMENTS_PROPERTIES_MAT),
]
