from infi.clickhouse_orm import migrations

from posthog.settings import CLICKHOUSE_CLUSTER

already_materialized_columns = [
    ("properties_issampledevent", "isSampledEvent"),
    ("properties_currentscreen", "currentScreen"),
    ("properties_objectname", "objectName"),
]

operations = []

for column_name, property in already_materialized_columns:
    statement = f"ALTER TABLE events ON CLUSTER '{CLICKHOUSE_CLUSTER}' COMMENT COLUMN IF EXISTS {column_name} 'column_materializer::{property}'"
    operations.append(migrations.RunSQL(statement))
