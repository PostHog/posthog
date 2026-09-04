# Test cases for clickhouse-migrations-no-drop-column-or-index rule.
# ruff: noqa: F821, E501
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

TABLE = "property_values"

# ruleid: clickhouse-migrations-no-drop-column-or-index
_drop_index = run_sql_with_exceptions("ALTER TABLE sharded_events DROP INDEX IF EXISTS `bloom_filter_$session_id`")

# ruleid: clickhouse-migrations-no-drop-column-or-index
_drop_column = run_sql_with_exceptions("ALTER TABLE sharded_events DROP COLUMN IF EXISTS mat_foo")

# ruleid: clickhouse-migrations-no-drop-column-or-index
_drop_index_fstring = run_sql_with_exceptions(f"ALTER TABLE {TABLE} DROP INDEX IF EXISTS idx_property_value")

# ok: clickhouse-migrations-no-drop-column-or-index
_add_index = run_sql_with_exceptions("ALTER TABLE sharded_events ADD INDEX IF NOT EXISTS i `$session_id` TYPE bloom_filter GRANULARITY 1")

# ok: clickhouse-migrations-no-drop-column-or-index
_add_column = run_sql_with_exceptions("ALTER TABLE sharded_events ADD COLUMN IF NOT EXISTS mat_foo String")

# ok: clickhouse-migrations-no-drop-column-or-index
_drop_table = run_sql_with_exceptions("DROP TABLE IF EXISTS events_tmp SYNC")

# ok: clickhouse-migrations-no-drop-column-or-index
_drop_partition = run_sql_with_exceptions("ALTER TABLE sharded_events DROP PARTITION '202001'")

# ok: clickhouse-migrations-no-drop-column-or-index
_applied_by_clickhouse_team = run_sql_with_exceptions("ALTER TABLE person DROP COLUMN IF EXISTS group_keys")  # nosemgrep: clickhouse-migrations-no-drop-column-or-index -- applied by the ClickHouse team on 2026-01-01, https://example.com/thread
