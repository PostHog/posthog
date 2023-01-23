from infi.clickhouse_orm import migrations

from posthog.models.person_overrides.sql import (
    KAFKA_PERSON_OVERRIDES_TABLE_SQL,
    PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL,
    PERSON_OVERRIDES_CREATE_TABLE_SQL,
)

operations = [
    migrations.RunSQL(PERSON_OVERRIDES_CREATE_TABLE_SQL),
    migrations.RunSQL(KAFKA_PERSON_OVERRIDES_TABLE_SQL),
    migrations.RunSQL(PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL),
]
