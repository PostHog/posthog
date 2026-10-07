from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person_group_membership.sql import (
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL,
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_TABLE_SQL,
    PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_SQL,
    PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL,
    SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE_SQL,
    WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
