from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_groups import property_groups
from posthog.models.flag_evaluations.sql import (
    FLAG_EVALUATIONS_DATA_TABLE,
    FLAG_EVALUATIONS_MAP_SERIALIZATION_SETTINGS,
    FLAG_EVALUATIONS_TABLE,
)
from posthog.run_mode import run_mode

# Adds the properties_group_feature_flags map to sharded_flag_evaluations and the flag_evaluations read table.
#
# Prod US and EU store sharded_flag_evaluations on the flags cluster, and both the flags and the data nodes carry a
# flag_evaluations read table. Dev and the local stacks keep the storage table and the read table on the data nodes.
#
# The setting change runs first.
# The first merge of a part written after the column exists then writes the bucketed layout.
# ClickHouse does not replicate a settings-only ALTER, so the setting change runs on every host of the storage role.
# The column ALTERs replicate, so each runs on one host per shard.
# The ALTERs change metadata only. A part written before them has no map files, and ClickHouse computes the map
# from the JSON when a query reads that part.


def operations_for(storage_role: NodeRole, read_table_roles: list[NodeRole]):
    return [
        run_sql_with_exceptions(
            f"ALTER TABLE {FLAG_EVALUATIONS_DATA_TABLE} MODIFY SETTING {FLAG_EVALUATIONS_MAP_SERIALIZATION_SETTINGS}",
            node_roles=[storage_role],
            sharded=True,
            is_alter_on_replicated_table=False,
        ),
        *[
            run_sql_with_exceptions(
                statement,
                node_roles=[storage_role],
                sharded=True,
                is_alter_on_replicated_table=True,
            )
            for statement in property_groups.get_alter_create_statements(
                FLAG_EVALUATIONS_DATA_TABLE, "properties", "feature_flags"
            )
        ],
        *[
            run_sql_with_exceptions(
                statement, node_roles=read_table_roles, sharded=False, is_alter_on_replicated_table=False
            )
            for statement in property_groups.get_alter_create_statements(
                FLAG_EVALUATIONS_TABLE, "properties", "feature_flags"
            )
        ],
    ]


operations = (
    operations_for(NodeRole.FLAGS, [NodeRole.DATA, NodeRole.FLAGS])
    if run_mode().is_prod_cloud
    else operations_for(NodeRole.DATA, [NodeRole.DATA])
)
