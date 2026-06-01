from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.cluster import NodeRole
from posthog.models.bot_definition.sql import (
    BOT_DEFINITION_DATA_SQL,
    BOT_DEFINITION_DICTIONARY_NAME,
    BOT_DEFINITION_DICTIONARY_SQL,
    BOT_DEFINITION_TABLE_SQL,
    BOT_DEFINITION_UDFS_SQL,
    TRUNCATE_BOT_DEFINITION_TABLE_SQL,
)


def _udf_sql(template: str) -> str:
    """Expand the {dict} placeholder to the fully-qualified dictionary name."""
    return template.format(dict=f"{settings.CLICKHOUSE_DATABASE}.{BOT_DEFINITION_DICTIONARY_NAME}")


# Bot detection is used from multiple query routes:
#   - DATA: events table queries (Trends, HogQL editor, custom insights, web-analytics live path)
#   - AUX: web-analytics preaggregated tables live on the aux cluster; future preagg query runners
#          that call __preview_isBot will resolve the dict there
#   - SESSIONS: session-replay-side queries can filter bots out of recording analytics
# Creating the table + dict + UDFs on each cluster gives us cluster-local lookups everywhere
# we might emit bot UDF calls — without it, queries dispatched outside DATA error out with
# `UNKNOWN_DICTIONARY`.
#
# TRUNCATE before INSERT so the migration is idempotent: any future re-run, or any
# follow-up migration that re-seeds bot data from a changed BOT_DEFINITIONS, lands on
# a clean table. BOT_DEFINITIONS in Python is the single source of truth.
NODE_ROLES = [NodeRole.DATA, NodeRole.AUX, NodeRole.SESSIONS]

operations = [
    run_sql_with_exceptions(BOT_DEFINITION_TABLE_SQL, node_roles=NODE_ROLES),
    run_sql_with_exceptions(TRUNCATE_BOT_DEFINITION_TABLE_SQL, node_roles=NODE_ROLES),
    run_sql_with_exceptions(BOT_DEFINITION_DATA_SQL, node_roles=NODE_ROLES),
    run_sql_with_exceptions(BOT_DEFINITION_DICTIONARY_SQL, node_roles=NODE_ROLES),
    *[run_sql_with_exceptions(_udf_sql(udf_sql), node_roles=NODE_ROLES) for udf_sql in BOT_DEFINITION_UDFS_SQL],
]
