from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_values_daily import (
    DISTRIBUTED_PROPERTY_VALUES_DAILY_TABLE_SQL,
    KAFKA_PROPERTY_VALUES_DAILY_TABLE_SQL_FN,
    PROPERTY_VALUES_DAILY_MV_SQL,
    PROPERTY_VALUES_DAILY_TABLE_SQL,
)

if settings.CLOUD_DEPLOYMENT in ("US", "EU"):
    _ROLES = [NodeRole.AUX]
    _DISTRIBUTED_ROLES = [NodeRole.AUX, NodeRole.DATA]
elif settings.CLOUD_DEPLOYMENT == "DEV":
    _ROLES = [NodeRole.DATA]
    _DISTRIBUTED_ROLES = [NodeRole.DATA]
else:
    _ROLES = []
    _DISTRIBUTED_ROLES = []

operations = (
    [
        run_sql_with_exceptions(
            PROPERTY_VALUES_DAILY_TABLE_SQL(),
            node_roles=_ROLES,
        ),
        run_sql_with_exceptions(
            KAFKA_PROPERTY_VALUES_DAILY_TABLE_SQL_FN(),
            node_roles=_ROLES,
        ),
        run_sql_with_exceptions(
            PROPERTY_VALUES_DAILY_MV_SQL(),
            node_roles=_ROLES,
        ),
        run_sql_with_exceptions(
            DISTRIBUTED_PROPERTY_VALUES_DAILY_TABLE_SQL(),
            node_roles=_DISTRIBUTED_ROLES,
        ),
    ]
    if _ROLES
    else []
)
