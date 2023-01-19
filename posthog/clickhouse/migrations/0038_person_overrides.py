from infi.clickhouse_orm import migrations

from posthog.models.person_overrides.sql import (
    PERSON_OVERRIDES_CREATE_KAFKA_TABLE_SQL,
    PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL,
    PERSON_OVERRIDES_CREATE_TABLE_SQL,
)

operations = [
    migrations.RunSQL(PERSON_OVERRIDES_CREATE_TABLE_SQL),
    migrations.RunSQL(PERSON_OVERRIDES_CREATE_KAFKA_TABLE_SQL),
    migrations.RunSQL(PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL),
]
