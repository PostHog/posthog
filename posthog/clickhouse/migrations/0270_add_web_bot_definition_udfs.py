from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.cluster import NodeRole
from posthog.models.bot_definition.sql import BOT_DEFINITION_DICTIONARY_NAME, BOT_DEFINITION_UDFS_SQL


def _udf_sql(template: str) -> str:
    """Expand the {dict} placeholder to the fully-qualified dictionary name."""
    return template.format(dict=f"{settings.CLICKHOUSE_DATABASE}.{BOT_DEFINITION_DICTIONARY_NAME}")


# UDFs land on the same node roles as the underlying dictionary — see migration 0269 for the
# rationale. Without this, queries that call botName/isBot/etc from anywhere outside DATA
# would error out with `Unknown function`.
NODE_ROLES = [NodeRole.DATA, NodeRole.AUX, NodeRole.SESSIONS]

operations = [run_sql_with_exceptions(_udf_sql(udf_sql), node_roles=NODE_ROLES) for udf_sql in BOT_DEFINITION_UDFS_SQL]
