from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person_group_membership.sql import (
    KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE,
    PERSON_GROUP_MEMBERSHIP_MV,
    PERSON_GROUP_MEMBERSHIP_MV_SELECT_SQL,
)

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {PERSON_GROUP_MEMBERSHIP_MV} MODIFY QUERY "
        f"{PERSON_GROUP_MEMBERSHIP_MV_SELECT_SQL(KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE)}",
        node_roles=[NodeRole.INGESTION_EVENTS],
        require_hosts=True,
    ),
]
