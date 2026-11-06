from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.messaging.backend.facade.clickhouse import (
    ADD_PROVIDER_MESSAGE_ID_TO_EMAIL_STATUS_EVENTS_DATA_SQL,
    ADD_PROVIDER_MESSAGE_ID_TO_EMAIL_STATUS_EVENTS_DISTRIBUTED_SQL,
    DROP_EMAIL_STATUS_EVENTS_MV_SQL,
    DROP_KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL,
    EMAIL_STATUS_EVENTS_MV_SQL,
    KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL,
)

# The Kafka table keeps its consumer group, so what's produced while the view is gone is read once it's back.
# The `email_status` feed reads the topic through its own table and is untouched.
operations = [
    run_sql_with_exceptions(DROP_EMAIL_STATUS_EVENTS_MV_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(DROP_KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(
        ADD_PROVIDER_MESSAGE_ID_TO_EMAIL_STATUS_EVENTS_DATA_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_PROVIDER_MESSAGE_ID_TO_EMAIL_STATUS_EVENTS_DISTRIBUTED_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(EMAIL_STATUS_EVENTS_MV_SQL(), node_roles=[NodeRole.AUX]),
]
