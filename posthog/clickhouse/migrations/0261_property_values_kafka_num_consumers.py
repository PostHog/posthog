from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_values import (
    DROP_KAFKA_PROPERTY_VALUES_TABLE_SQL,
    DROP_PROPERTY_VALUES_MV_SQL,
    KAFKA_PROPERTY_VALUES_TABLE_SQL_FN,
    PROPERTY_VALUES_MV_SQL,
)

# Kafka engine tables can't be ALTER-ed to change SETTINGS, so we drop and
# recreate the MV + Kafka engine table together. Consumer group offsets live
# in Kafka, not in CH, so the recreated table resumes at the last committed
# offset. Brief window (~seconds) during the migration where new produces sit
# in the topic waiting for the new MV; backlog drains after.

if settings.CLOUD_DEPLOYMENT == "DEV":
    _ROLES = [NodeRole.DATA]
else:
    _ROLES = [NodeRole.AUX]

operations = [
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
