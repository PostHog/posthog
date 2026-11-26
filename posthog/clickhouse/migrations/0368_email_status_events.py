from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.messaging.backend.facade.clickhouse import (
    ALTER_EMAIL_STATUS_MV_QUERY_SQL,
    DISTRIBUTED_EMAIL_STATUS_EVENTS_TABLE_SQL,
    EMAIL_STATUS_EVENTS_DATA_TABLE_SQL,
    EMAIL_STATUS_EVENTS_MV_SQL,
    KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL,
)

# Only adds objects: the new table reads the topic through its own Kafka table and consumer group, and the
# existing view keeps consuming while its query changes in place, so the email_status feed never pauses.
operations = [
    run_sql_with_exceptions(EMAIL_STATUS_EVENTS_DATA_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(EMAIL_STATUS_EVENTS_MV_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(
        ALTER_EMAIL_STATUS_MV_QUERY_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(DISTRIBUTED_EMAIL_STATUS_EVENTS_TABLE_SQL(), node_roles=[NodeRole.AUX, NodeRole.DATA]),
]
