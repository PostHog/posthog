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
        f"ALTER TABLE {TABLE_NAME} MODIFY TTL last_seen + INTERVAL 7 DAY DELETE SETTINGS materialize_ttl_after_modify = 1",
        node_roles=_ROLES,
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
