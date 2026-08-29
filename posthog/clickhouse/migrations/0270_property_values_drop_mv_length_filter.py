from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_values import DROP_PROPERTY_VALUES_MV_SQL, PROPERTY_VALUES_MV_SQL
from posthog.run_mode import run_mode

# Length and empty-value filtering now lives in the property-vals service, so the
# MV passes everything from the Kafka table straight through. property_values lives
# on AUX in every cloud env. Single-node local/hobby get overridden to ALL by
# the migration runner.
_ROLES = [NodeRole.AUX]

operations = (
    [
        run_sql_with_exceptions(DROP_PROPERTY_VALUES_MV_SQL(), node_roles=_ROLES),
        run_sql_with_exceptions(PROPERTY_VALUES_MV_SQL(), node_roles=_ROLES),
    ]
    if run_mode().is_deployed_cloud
    else []
)
