from functools import lru_cache

import structlog
from infi.clickhouse_orm import migrations

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.columns import get_materialized_columns, materialized_column_name
from posthog.constants import GROUP_TYPES_LIMIT
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

logger = structlog.get_logger(__name__)


def alias_column(table, current_name, new_name):
    execute_on_cluster = f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if table == "events" else ""
    sync_execute(
        f"""
        ALTER TABLE {table} {execute_on_cluster}
        ADD COLUMN IF NOT EXISTS \"{new_name}\"
        VARCHAR ALIAS \"{current_name}\"
    """
    )

    comment = get_column_names(table)[current_name]
    if len(comment) > 0:
        comment_column(table, current_name, "")
        comment_column(table, new_name, comment)

    logger.info(
        "Created an ALIAS for column containing $ sign.", table=table, current_name=current_name, new_name=new_name
    )


def alias_column_if_exists(table, current_name, new_name):
    if current_name in get_column_names(table) and new_name not in get_column_names(table):
        alias_column(table, current_name, new_name)
    else:
        logger.info("No need to ALIAS column, ignoring.", table=table, current_name=current_name, new_name=new_name)


@lru_cache(maxsize=None)
def get_column_names(table: str):
    rows = sync_execute(
        "SELECT name, comment FROM system.columns WHERE database = %(database)s AND table = %(table)s",
        {"database": CLICKHOUSE_DATABASE, "table": table},
    )
    return dict(rows)


def comment_column(table, name, comment):
    execute_on_cluster = f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if table == "events" else ""
    sync_execute(
        f"""
        ALTER TABLE {table} {execute_on_cluster}
        COMMENT COLUMN \"{name}\" %(comment)s
        """,
        {"comment": comment},
    )


def rename_materialized_columns_with_dollars(database):
    for i in range(GROUP_TYPES_LIMIT):
        alias_column_if_exists("events", f"$group_{i}", f"group_{i}")
    alias_column_if_exists("events", "$window_id", "mat_window_id")
    alias_column_if_exists("events", "$session_id", "mat_session_id")

    for table in ("events", "person"):
        for property, column_name in get_materialized_columns(table, use_cache=False).items():
            if "$" not in column_name:
                continue

            new_column_name = "alias_" + materialized_column_name(table, property)  # type: ignore
            alias_column(table, column_name, new_column_name)


operations = [migrations.RunPython(rename_materialized_columns_with_dollars)]
