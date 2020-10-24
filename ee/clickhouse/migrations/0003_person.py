from infi.clickhouse_orm import migrations  # type: ignore

from ee.clickhouse.sql.person import PERSONS_DISTINCT_ID_TABLE_SQL, PERSONS_TABLE_SQL
from ee.dynamodb.events import ensure_events_table

operations = [
    migrations.RunSQL(PERSONS_TABLE_SQL),
    migrations.RunSQL(PERSONS_DISTINCT_ID_TABLE_SQL),
    migrations.RunPython(ensure_events_table),
]
