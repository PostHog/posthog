from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
<<<<<<< Updated upstream
=======
from django.conf import settings
>>>>>>> Stashed changes

already_materialized_columns = [
    ("properties_issampledevent", "isSampledEvent"),
    ("properties_currentscreen", "currentScreen"),
    ("properties_objectname", "objectName"),
]

operations = []

for column_name, property in already_materialized_columns:
    statement = f"ALTER TABLE events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' COMMENT COLUMN IF EXISTS {column_name} 'column_materializer::{property}'"
    operations.append(run_sql_with_exceptions(statement))
