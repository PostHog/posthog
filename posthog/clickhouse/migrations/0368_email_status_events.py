from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.messaging.backend.facade.clickhouse import (
    DISTRIBUTED_EMAIL_STATUS_EVENTS_TABLE_SQL,
    EMAIL_STATUS_EVENTS_DATA_TABLE_SQL,
    EMAIL_STATUS_EVENTS_MV_SQL,
    EMAIL_STATUS_MV_SQL,
    KAFKA_EMAIL_STATUS_TABLE_SQL,
)

# A Kafka table's columns are fixed at creation, so it is dropped and recreated with the new columns,
# together with the MV that reads it. Neither is replicated, so no SYNC. The recreated table keeps its
# consumer group, so rows produced in between are read once the MVs exist again.
operations = [
    run_sql_with_exceptions(EMAIL_STATUS_EVENTS_DATA_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS email_status_mv", node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS kafka_email_status", node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(KAFKA_EMAIL_STATUS_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(EMAIL_STATUS_MV_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(EMAIL_STATUS_EVENTS_MV_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(DISTRIBUTED_EMAIL_STATUS_EVENTS_TABLE_SQL(), node_roles=[NodeRole.AUX, NodeRole.DATA]),
]
