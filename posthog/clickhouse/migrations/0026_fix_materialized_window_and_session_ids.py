from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.materialized_columns import get_materialized_column_for_property
from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER
from posthog.settings.data_stores import CLICKHOUSE_DATABASE


def does_column_exist(table_name, column_name):
    cols = sync_execute(
        f"""
            SELECT 1
            FROM system.columns
            WHERE table = '{table_name}' AND name = '{column_name}' AND database = '{CLICKHOUSE_DATABASE}'
        """
    )
    return len(cols) == 1


def ensure_only_new_column_exists(table_name, old_column_name, new_column_name, node_role):
    if does_column_exist(table_name, new_column_name):
        # New column already exists, so just drop the old one
        return run_sql_with_exceptions(
            f"""
                ALTER TABLE {table_name}
                {"ON CLUSTER '{cluster}'".format(cluster=CLICKHOUSE_CLUSTER) if node_role == NodeRole.WORKER else ""}
                DROP COLUMN IF EXISTS {old_column_name}
            """,
            node_role=node_role,
        )
    else:
        # New column does not exist, so rename the old one to the new one
        return run_sql_with_exceptions(
            f"""
                ALTER TABLE {table_name}
                {"ON CLUSTER '{cluster}'".format(cluster=CLICKHOUSE_CLUSTER) if node_role == NodeRole.WORKER else ""}
                RENAME COLUMN IF EXISTS {old_column_name} TO {new_column_name}
            """,
            node_role=node_role,
        )


def materialize_session_and_window_id():
    try:
        from ee.clickhouse.materialized_columns.columns import materialize
    except ImportError:
        return

    operations = []

    properties = ["$session_id", "$window_id"]
    for property_name in properties:
        current_materialized_column = get_materialized_column_for_property("events", "properties", property_name)
        # If the column is not materialized, materialize it
        if current_materialized_column is None:
            materialize("events", property_name, property_name)

        # Now, we need to clean up any potentail inconsistencies with existing column names
        # Possible states are:
        # * Materialized column exists, and is named correctly -> nothing to do
        # * Materialized column exists, but is named incorrectly -> rename it
        # * Materialized column exists, but it's inconsistently named between events and sharded_events -> rename the incorrect table only

        # First, we create a list of possible column names that need to be cleaned up
        # mat_{property_name} is the expected old name, so we explicitly add that one
        # to handle cases where the column names are inconsistent, but it could
        # technically also have a name like mat_{property_name}_{unique random string} if the
        # customer manually materialized the column and on cloud, it got manually renamed to
        # mat_session_id instead of mat_$session_id so we handle those cases by checking the
        # currently materialized column name in addition to the expected old name.

        # NOTE: This does not handle a very unexpected, but potential state where the
        # columns are in an inconsistent state between events and sharded_events,
        # and the incorrect column is on the sharded_events table and it's not the
        # expected mat_{property_name}. However, that would only happen if the customer manually
        # materialized the column or renamed the column, and then ran the 0004_...  async migration
        # before this migration runs.
        possible_old_column_names = {"mat_" + property_name}
        if current_materialized_column is not None and current_materialized_column.name != property_name:
            possible_old_column_names.add(current_materialized_column.name)

        for possible_old_column_name in possible_old_column_names:
            operations.append(
                ensure_only_new_column_exists(
                    "sharded_events", possible_old_column_name, property_name, node_role=NodeRole.WORKER
                )
            )
            operations.append(
                ensure_only_new_column_exists(
                    "events", possible_old_column_name, property_name, node_role=NodeRole.WORKER
                )
            )
            operations.append(
                ensure_only_new_column_exists(
                    "events", possible_old_column_name, property_name, node_role=NodeRole.COORDINATOR
                )
            )

    return operations


operations = materialize_session_and_window_id()
