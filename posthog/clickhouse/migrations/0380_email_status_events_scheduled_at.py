from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.messaging.backend.facade.clickhouse import (
    ADD_SCHEDULED_AT_TO_EMAIL_STATUS_EVENTS_DATA_SQL,
    ADD_SCHEDULED_AT_TO_EMAIL_STATUS_EVENTS_SQL,
    DROP_EMAIL_STATUS_EVENTS_MV_SQL,
    DROP_KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL,
    EMAIL_STATUS_EVENTS_MV_SQL,
    KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL,
)

# The view goes first, so no row is read from the topic until the storage table has the column. The new Kafka
# table joins the same consumer group, so rows sent meanwhile arrive late, not lost. email_status is untouched.
operations = [
    run_sql_with_exceptions(DROP_EMAIL_STATUS_EVENTS_MV_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(DROP_KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(
        ADD_SCHEDULED_AT_TO_EMAIL_STATUS_EVENTS_DATA_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    # A Distributed table stores no rows, so every node that has one changes its own copy.
    run_sql_with_exceptions(
        ADD_SCHEDULED_AT_TO_EMAIL_STATUS_EVENTS_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(EMAIL_STATUS_EVENTS_MV_SQL(), node_roles=[NodeRole.AUX]),
]
