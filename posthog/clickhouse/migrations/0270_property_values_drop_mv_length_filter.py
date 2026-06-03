from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_values import DROP_PROPERTY_VALUES_MV_SQL, PROPERTY_VALUES_MV_SQL

# Length and empty-value filtering now lives in the property-vals service, so
# the MV passes everything from the Kafka table straight through.

# AUX in US/EU; DATA everywhere else (DEV, plus local/hobby where the runner
# overrides node roles to ALL on the single-node CH).
_ROLES = [NodeRole.AUX] if settings.CLOUD_DEPLOYMENT in ("US", "EU") else [NodeRole.DATA]

operations = [
    run_sql_with_exceptions(DROP_PROPERTY_VALUES_MV_SQL(), node_roles=_ROLES),
    run_sql_with_exceptions(PROPERTY_VALUES_MV_SQL(), node_roles=_ROLES),
]
