"""Store what the source said about each check, so a message can quote it without reading Postgres."""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.alerts_platform.backend.facade.clickhouse import (
    PLATFORM_ALERT_EVENTS_TABLE,
    SHARDED_PLATFORM_ALERT_EVENTS_TABLE,
)

# Unqualified, as in 0346, so the ALTER reaches the tables in the configured database. Positioned
# rather than appended, so the column order matches the declarative schema.
ADD_SOURCE_DETAIL = "ADD COLUMN IF NOT EXISTS source_detail String AFTER source_config_snapshot"

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {SHARDED_PLATFORM_ALERT_EVENTS_TABLE} {ADD_SOURCE_DETAIL}",
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {PLATFORM_ALERT_EVENTS_TABLE} {ADD_SOURCE_DETAIL}",
        node_roles=[NodeRole.DATA, NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
