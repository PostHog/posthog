from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person_group_membership.sql import (
    KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE_SQL,
    PERSON_GROUP_MEMBERSHIP_MV_SQL,
)

operations = [
    run_sql_with_exceptions(
        KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        PERSON_GROUP_MEMBERSHIP_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
