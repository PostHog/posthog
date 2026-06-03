from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_values import DROP_PROPERTY_VALUES_MV_SQL, PROPERTY_VALUES_MV_SQL

# Length and empty-value filtering now lives in the property-vals service, so the
# MV passes everything from the Kafka table straight through. Target NodeRole.AUX
# to match where 0244 created the MV; single-node local/hobby get overridden to
# ALL by the migration runner, so the drop lands there too.
operations = [
    run_sql_with_exceptions(DROP_PROPERTY_VALUES_MV_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(PROPERTY_VALUES_MV_SQL(), node_roles=[NodeRole.AUX]),
]
