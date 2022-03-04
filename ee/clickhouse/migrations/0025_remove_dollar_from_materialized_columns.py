import structlog
from clickhouse_driver.errors import ServerException
from infi.clickhouse_orm import migrations

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.columns import get_materialized_columns, materialized_column_name
from posthog.constants import GROUP_TYPES_LIMIT
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_REPLICATION

logger = structlog.get_logger(__name__)


def rename_column(table, current_name, new_name):
    if CLICKHOUSE_REPLICATION and table == "events":
        sync_execute(
            f"ALTER TABLE {table} RENAME COLUMN \"{current_name}\" TO {new_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
        )
        sync_execute(
            f"ALTER TABLE sharded_{table} RENAME COLUMN \"{current_name}\" TO {new_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
        )
    else:
        sync_execute(f'ALTER TABLE {table} RENAME COLUMN "{current_name}" TO {new_name}')
    logger.info("Renamed column containing $ sign.", table=table, current_name=current_name, new_name=new_name)


def rename_column_if_exists(table, current_name, new_name):
    try:
        rename_column(table, current_name, new_name)
    except ServerException as err:
        logger.info("Column already renamed, ignoring.", table=table, current_name=current_name, new_name=new_name)


def rename_materialized_columns_with_dollars(database):
    for i in range(GROUP_TYPES_LIMIT):
        rename_column_if_exists("events", f"$group_{i}", f"group_{i}")
    rename_column_if_exists("events", "$window_id", "mat_window_id")
    rename_column_if_exists("events", "$session_id", "mat_session_id")

    for table in ("events", "person"):
        for property, column_name in get_materialized_columns(table, use_cache=False).items():
            if "$" not in column_name:
                continue

            new_column_name = materialized_column_name(table, property)  # type: ignore
            rename_column(table, column_name, new_column_name)


operations = [migrations.RunPython(rename_materialized_columns_with_dollars)]
