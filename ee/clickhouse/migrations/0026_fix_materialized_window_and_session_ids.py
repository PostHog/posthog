from infi.clickhouse_orm import migrations

from ee.clickhouse.materialized_columns.columns import get_materialized_columns, materialize, materialized_column_name
from ee.clickhouse.materialized_columns.replication import clickhouse_is_replicated
from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER


def rename_column_on_events_table(old_column_name, new_column_name):
    if clickhouse_is_replicated():
        sync_execute(
            f"""
                ALTER TABLE sharded_events
                ON CLUSTER '{CLICKHOUSE_CLUSTER}'
                RENAME COLUMN IF EXISTS {old_column_name} to {new_column_name}
            """
        )
    sync_execute(
        f"""
            ALTER TABLE events
            ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            RENAME COLUMN IF EXISTS {old_column_name} to {new_column_name}
        """
    )


def create_materialized_columns(database):
    properties = ["$session_id", "$window_id"]
    for property in properties:
        try:
            materialize("events", property)
        except ValueError:
            # property is already materialized. Now, ensure the column's name is correct.
            # This handles the case where the bad 0024_materialize_window_and_session_id
            # already ran
            materialized_columns = get_materialized_columns("events", use_cache=False)
            current_materialized_column_name = materialized_columns.get(property, None)
            expected_materialized_column_name = materialized_column_name("events", property)
            if (
                current_materialized_column_name
                and current_materialized_column_name != expected_materialized_column_name
            ):
                rename_column_on_events_table(current_materialized_column_name, expected_materialized_column_name)


operations = [migrations.RunPython(create_materialized_columns)]
