"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.

Edited after generation to build the DDL from the Python definitions rather than the literal SQL
the generator emits. The generator qualifies every name with the database the HCL declares, which
is `posthog` on the aux role, and a test or local ClickHouse runs under a different database.
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.alerts.backend.models.platform_alert_events_sql import (
    DISTRIBUTED_PLATFORM_ALERT_EVENTS_TABLE_SQL,
    SHARDED_PLATFORM_ALERT_EVENTS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        SHARDED_PLATFORM_ALERT_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_PLATFORM_ALERT_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
