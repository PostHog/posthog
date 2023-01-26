from infi.clickhouse_orm import migrations

from posthog.models.person_overrides.sql import PERSON_OVERRIDES_CREATE_DICTIONARY_SQL

operations = [
    migrations.RunSQL(PERSON_OVERRIDES_CREATE_DICTIONARY_SQL),
]
