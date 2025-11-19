from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions


def generate_add_columns_sharded_events() -> str:
    """Generate ALTER TABLE statement for sharded_events with all 40 columns."""
    statements = []

    # Add string columns (0-9)
    for i in range(10):
        statements.append(f"ADD COLUMN IF NOT EXISTS `dmat_string_{i}` Nullable(String)")

    # Add float columns (0-9)
    for i in range(10):
        statements.append(f"ADD COLUMN IF NOT EXISTS `dmat_float_{i}` Nullable(Float64)")

    # Add bool columns (0-9)
    for i in range(10):
        statements.append(f"ADD COLUMN IF NOT EXISTS `dmat_bool_{i}` Nullable(UInt8)")

    # Add datetime columns (0-9)
    for i in range(10):
        statements.append(f"ADD COLUMN IF NOT EXISTS `dmat_datetime_{i}` Nullable(DateTime64(6, 'UTC'))")

    return f"ALTER TABLE sharded_events\n{',\n'.join(statements)}"


def generate_add_columns_events() -> str:
    """Generate ALTER TABLE statement for events with all 40 columns."""
    statements = []

    # Add string columns (0-9)
    for i in range(10):
        statements.append(f"ADD COLUMN IF NOT EXISTS `dmat_string_{i}` Nullable(String)")

    # Add float columns (0-9)
    for i in range(10):
        statements.append(f"ADD COLUMN IF NOT EXISTS `dmat_float_{i}` Nullable(Float64)")

    # Add bool columns (0-9)
    for i in range(10):
        statements.append(f"ADD COLUMN IF NOT EXISTS `dmat_bool_{i}` Nullable(UInt8)")

    # Add datetime columns (0-9)
    for i in range(10):
        statements.append(f"ADD COLUMN IF NOT EXISTS `dmat_datetime_{i}` Nullable(DateTime64(6, 'UTC'))")

    return f"ALTER TABLE events\n{',\n'.join(statements)}"


ADD_COLUMNS_SHARDED_EVENTS = generate_add_columns_sharded_events()
ADD_COLUMNS_EVENTS = generate_add_columns_events()

operations = [
    run_sql_with_exceptions(
        ADD_COLUMNS_SHARDED_EVENTS,
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_COLUMNS_EVENTS,
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
