from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_values import (
    DROP_KAFKA_PROPERTY_VALUES_TABLE_SQL,
    DROP_PROPERTY_VALUES_MV_SQL,
    KAFKA_PROPERTY_VALUES_TABLE_SQL_FN,
    PROPERTY_VALUES_MV_SQL,
    PROPERTY_VALUES_TABLE_SQL,
)
from posthog.run_mode import run_mode

# Fix to 0244: kafka_property_values used the default msk_cluster named
# collection, but the topic is produced to warpstream_ingestion. Drop the MV
# first, then the Kafka table, then recreate both with the right named
# collection. Storage table is untouched. The property_values pipeline lives
# on AUX in every cloud env.

if run_mode().is_deployed_cloud:
    operations = [
        run_sql_with_exceptions(PROPERTY_VALUES_TABLE_SQL(), node_roles=[NodeRole.AUX]),
        run_sql_with_exceptions(DROP_PROPERTY_VALUES_MV_SQL(), node_roles=[NodeRole.AUX]),
        run_sql_with_exceptions(DROP_KAFKA_PROPERTY_VALUES_TABLE_SQL(), node_roles=[NodeRole.AUX]),
        run_sql_with_exceptions(KAFKA_PROPERTY_VALUES_TABLE_SQL_FN(), node_roles=[NodeRole.AUX]),
        run_sql_with_exceptions(PROPERTY_VALUES_MV_SQL(), node_roles=[NodeRole.AUX]),
    ]
else:
    operations = []
