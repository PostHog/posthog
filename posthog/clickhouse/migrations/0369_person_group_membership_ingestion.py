from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person_group_membership.sql import (
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL,
    KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE_SQL,
    PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_SQL,
    PERSON_GROUP_MEMBERSHIP_MV_SQL,
    WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_EVENTS],
        require_hosts=True,
    ),
    run_sql_with_exceptions(
        PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_SQL(),
        node_roles=[NodeRole.INGESTION_EVENTS],
        require_hosts=True,
    ),
    run_sql_with_exceptions(
        WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_EVENTS],
        require_hosts=True,
    ),
    run_sql_with_exceptions(
        KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_EVENTS],
        require_hosts=True,
    ),
    run_sql_with_exceptions(
        PERSON_GROUP_MEMBERSHIP_MV_SQL(),
        node_roles=[NodeRole.INGESTION_EVENTS],
        require_hosts=True,
    ),
]
