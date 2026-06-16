from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.bot_definition.sql import BOT_DEFINITION_UDFS_SQL

operations = [run_sql_with_exceptions(sql, node_roles=[NodeRole.DATA, NodeRole.AUX]) for sql in BOT_DEFINITION_UDFS_SQL]
