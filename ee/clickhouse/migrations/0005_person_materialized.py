from infi.clickhouse_orm import migrations  # type: ignore

from ee.clickhouse.sql.person import (
    MAT_PERSONS_PROP_TABLE_SQL,
    MAT_PERSONS_WITH_PROPS_TABLE_SQL,
    PERSONS_UP_TO_DATE_MATERIALIZED_VIEW,
    PERSONS_UP_TO_DATE_VIEW,
    PERSONS_WITH_PROPS_TABLE_SQL,
)

operations = [
    migrations.RunSQL(PERSONS_UP_TO_DATE_MATERIALIZED_VIEW),
    migrations.RunSQL(PERSONS_UP_TO_DATE_VIEW),
    migrations.RunSQL(PERSONS_WITH_PROPS_TABLE_SQL),
    migrations.RunSQL(MAT_PERSONS_WITH_PROPS_TABLE_SQL),
    migrations.RunSQL(MAT_PERSONS_PROP_TABLE_SQL),
]
