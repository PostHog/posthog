from infi.clickhouse_orm import migrations  # type: ignore

from ee.clickhouse.sql.retention import PERSON_RETENTION_PERIOD_MV

operations = [
    migrations.RunSQL(PERSON_RETENTION_PERIOD_MV),
]
