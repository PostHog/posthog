from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_values import (
    DROP_KAFKA_PROPERTY_VALUES_TABLE_SQL,
    DROP_PROPERTY_VALUES_MV_SQL,
    KAFKA_PROPERTY_VALUES_TABLE_SQL_FN,
    PROPERTY_VALUES_MV_SQL,
)

# Kafka engine tables don't support ALTER ADD COLUMN, so we drop and recreate
# the MV + Kafka engine table together.

if settings.CLOUD_DEPLOYMENT in ("US", "EU"):
    _ROLES = [NodeRole.AUX]
elif settings.CLOUD_DEPLOYMENT == "DEV":
    _ROLES = [NodeRole.DATA]
else:
    _ROLES = []

operations = (
    [
        run_sql_with_exceptions(
            DROP_PROPERTY_VALUES_MV_SQL(),
            node_roles=_ROLES,
        ),
        run_sql_with_exceptions(
            DROP_KAFKA_PROPERTY_VALUES_TABLE_SQL(),
            node_roles=_ROLES,
        ),
        run_sql_with_exceptions(
            KAFKA_PROPERTY_VALUES_TABLE_SQL_FN(),
            node_roles=_ROLES,
        ),
        run_sql_with_exceptions(
            PROPERTY_VALUES_MV_SQL(),
            node_roles=_ROLES,
        ),
    ]
    if _ROLES
    else []
)
