from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_groups import flag_evaluations_property_group_definitions, iter_groups, property_groups
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_DATA_TABLE, FLAG_EVALUATIONS_TABLE

# Adds the property-group map columns to sharded_flag_evaluations and the flag_evaluations read
# table. posthog/models/flag_evaluations/sql.py carries the rationale.
#
# The ALTERs change metadata only. A part written before them has no map files, and ClickHouse
# computes the maps from the JSON when a query reads that part. writable_flag_evaluations stays
# as it is, so inserts arrive without the maps and the shards compute them.

operations = [
    *[
        run_sql_with_exceptions(
            statement,
            node_roles=[NodeRole.DATA],
            sharded=True,
            is_alter_on_replicated_table=True,
        )
        for group in iter_groups(flag_evaluations_property_group_definitions)
        for statement in property_groups.get_alter_create_statements(
            FLAG_EVALUATIONS_DATA_TABLE, group.source_column, group.group_name
        )
    ],
    *[
        run_sql_with_exceptions(
            statement,
            node_roles=[NodeRole.DATA],
            sharded=False,
            is_alter_on_replicated_table=False,
        )
        for group in iter_groups(flag_evaluations_property_group_definitions)
        for statement in property_groups.get_alter_create_statements(
            FLAG_EVALUATIONS_TABLE, group.source_column, group.group_name
        )
    ],
]
