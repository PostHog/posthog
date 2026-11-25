from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person_group_membership.sql import (
    KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE,
    KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE_SQL,
    PERSON_GROUP_MEMBERSHIP_MV,
    PERSON_GROUP_MEMBERSHIP_MV_SQL,
)

# The view filters on the event name, so the Kafka table must read the event column.
# ClickHouse fixes a Kafka table's columns at creation.
# This migration therefore drops and recreates the table and its view.
# The new table keeps the consumer group. Consumption therefore resumes from the committed offsets.
operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{PERSON_GROUP_MEMBERSHIP_MV}",
        node_roles=[NodeRole.INGESTION_EVENTS],
        require_hosts=True,
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE}",
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
