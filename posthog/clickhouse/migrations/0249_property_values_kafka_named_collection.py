from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_values import (
    DROP_KAFKA_PROPERTY_VALUES_TABLE_SQL,
    DROP_PROPERTY_VALUES_MV_SQL,
    KAFKA_PROPERTY_VALUES_TABLE_SQL_FN,
    PROPERTY_VALUES_MV_SQL,
    PROPERTY_VALUES_TABLE_SQL,
)

# Two fixes to 0244:
# - US/EU: kafka_property_values used the default msk_cluster named collection,
#   but the topic is produced to warpstream_ingestion. Drop the MV first, then
#   the Kafka table, then recreate both with the right named collection.
#   Storage table is untouched.
# - DEV: 0244's AUX ops no-op'd because dev has no hostClusterRole=aux nodes.
#   Create storage, Kafka, and MV on DATA. Dev's `aux` cluster aliases to those
#   same hosts so the existing Distributed proxy resolves correctly.

if settings.CLOUD_DEPLOYMENT in ("US", "EU"):
    operations = [
        run_sql_with_exceptions(DROP_PROPERTY_VALUES_MV_SQL(), node_roles=[NodeRole.AUX]),
        run_sql_with_exceptions(DROP_KAFKA_PROPERTY_VALUES_TABLE_SQL(), node_roles=[NodeRole.AUX]),
        run_sql_with_exceptions(KAFKA_PROPERTY_VALUES_TABLE_SQL_FN(), node_roles=[NodeRole.AUX]),
        run_sql_with_exceptions(PROPERTY_VALUES_MV_SQL(), node_roles=[NodeRole.AUX]),
    ]
elif settings.CLOUD_DEPLOYMENT == "DEV":
    operations = [
        run_sql_with_exceptions(PROPERTY_VALUES_TABLE_SQL(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(KAFKA_PROPERTY_VALUES_TABLE_SQL_FN(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(PROPERTY_VALUES_MV_SQL(), node_roles=[NodeRole.DATA]),
    ]
else:
    operations = []
