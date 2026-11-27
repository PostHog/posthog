from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.messaging.backend.facade.clickhouse import (
    ADD_PROVIDER_MESSAGE_ID_TO_EMAIL_STATUS_EVENTS_DATA_SQL,
    ADD_PROVIDER_MESSAGE_ID_TO_EMAIL_STATUS_EVENTS_SQL,
    DROP_EMAIL_STATUS_EVENTS_MV_SQL,
    DROP_KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL,
    EMAIL_STATUS_EVENTS_MV_SQL,
    KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL,
)

# The columns go in while the old view still consumes, because it writes only the columns it selects. Only then
# are the view and the Kafka table replaced, so ingestion pauses for the two CREATE statements alone. The new Kafka
# table joins the same consumer group, so rows sent meanwhile arrive late, not lost. email_status is untouched.
operations = [
    run_sql_with_exceptions(
        ADD_PROVIDER_MESSAGE_ID_TO_EMAIL_STATUS_EVENTS_DATA_SQL,
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    # A Distributed table stores no rows, so every node that has one changes its own copy.
    run_sql_with_exceptions(
        ADD_PROVIDER_MESSAGE_ID_TO_EMAIL_STATUS_EVENTS_SQL,
        node_roles=[NodeRole.AUX, NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(DROP_EMAIL_STATUS_EVENTS_MV_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(DROP_KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(EMAIL_STATUS_EVENTS_MV_SQL(), node_roles=[NodeRole.AUX]),
]
