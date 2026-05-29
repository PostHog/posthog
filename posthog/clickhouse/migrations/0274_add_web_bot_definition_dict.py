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


# TRUNCATE before INSERT so the migration is idempotent: any future re-run, or any
# follow-up migration that re-seeds bot data from a changed BOT_DEFINITIONS, lands on
# a clean table. BOT_DEFINITIONS in Python is the single source of truth.
operations = [
    run_sql_with_exceptions(BOT_DEFINITION_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(TRUNCATE_BOT_DEFINITION_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(BOT_DEFINITION_DATA_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(BOT_DEFINITION_DICTIONARY_SQL, node_roles=[NodeRole.DATA]),
    *[run_sql_with_exceptions(_udf_sql(udf_sql), node_roles=[NodeRole.DATA]) for udf_sql in BOT_DEFINITION_UDFS_SQL],
]
