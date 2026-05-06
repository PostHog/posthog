from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

if settings.CLOUD_DEPLOYMENT in ("US", "EU"):
    _ROLES = [NodeRole.AUX]
elif settings.CLOUD_DEPLOYMENT == "DEV":
    _ROLES = [NodeRole.DATA]
else:
    _ROLES = []

operations = (
    [
        run_sql_with_exceptions(
            "ALTER TABLE property_values DROP INDEX IF EXISTS idx_property_value",
            node_roles=_ROLES,
            is_alter_on_replicated_table=True,
        ),
        run_sql_with_exceptions(
            "ALTER TABLE property_values ADD INDEX IF NOT EXISTS idx_property_value property_value "
            "TYPE text(tokenizer = ngrams(3), preprocessor = lower(property_value)) GRANULARITY 1",
            node_roles=_ROLES,
            is_alter_on_replicated_table=True,
        ),
        run_sql_with_exceptions(
            "ALTER TABLE property_values MATERIALIZE INDEX idx_property_value",
            node_roles=_ROLES,
            is_alter_on_replicated_table=True,
        ),
    ]
    if _ROLES
    else []
)
