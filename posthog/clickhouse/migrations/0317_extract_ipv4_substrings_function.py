from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs.functions import EXTRACT_IPV4_SUBSTRINGS_FUNCTION_SQL

operations = [
    run_sql_with_exceptions(EXTRACT_IPV4_SUBSTRINGS_FUNCTION_SQL(), node_roles=[NodeRole.LOGS]),
]
