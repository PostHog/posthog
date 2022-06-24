from infi.clickhouse_orm import migrations

from posthog.models.person.sql import (
    KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL,
    PERSON_DISTINCT_ID2_MV_SQL,
    PERSON_DISTINCT_ID2_TABLE_SQL,
)

operations = [
    migrations.RunSQL(PERSON_DISTINCT_ID2_TABLE_SQL()),
    migrations.RunSQL(KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL()),
    migrations.RunSQL(PERSON_DISTINCT_ID2_MV_SQL,),
]
