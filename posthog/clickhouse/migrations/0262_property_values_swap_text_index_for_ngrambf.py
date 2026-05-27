from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_values import TABLE_NAME

if settings.CLOUD_DEPLOYMENT == "DEV":
    _ROLES = [NodeRole.DATA]
else:
    _ROLES = [NodeRole.AUX]

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {TABLE_NAME} DROP INDEX IF EXISTS idx_property_value",
        node_roles=_ROLES,
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {TABLE_NAME} ADD INDEX IF NOT EXISTS idx_property_value_ngrambf lower(property_value) TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1",
        node_roles=_ROLES,
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {TABLE_NAME} MATERIALIZE INDEX idx_property_value_ngrambf",
        node_roles=_ROLES,
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
