from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ai_events.sql import (
    AI_EVENTS_DATA_TABLE_SQL,
    AI_EVENTS_MV_SQL,
    DISTRIBUTED_AI_EVENTS_TABLE_SQL,
    KAFKA_AI_EVENTS_TABLE_SQL,
    TABLE_BASE_NAME,
)

# Bootstrap the ai_events data, distributed, and MSK Kafka + MV tables on the
# ai_events satellite cluster via the standard migration flow. Replaces
# bin/clickhouse-ai-events-init, which existed only because the CH migration
# runner couldn't target satellite clusters until PR #53169.
#
# Idempotent by design: in prod (US/EU) and cloud DEV, the data + distributed
# tables were created by migration 0232, and the MSK Kafka table + MV were
# created out-of-band. `CREATE TABLE IF NOT EXISTS` keeps those intact and
# fills the gap in local dev / hobby, where 0232 is no-op'd by its
# CLOUD_DEPLOYMENT gate.

operations = [
    run_sql_with_exceptions(
        AI_EVENTS_DATA_TABLE_SQL(),
        node_roles=[NodeRole.AI_EVENTS],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_AI_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AI_EVENTS, NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        KAFKA_AI_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AI_EVENTS],
    ),
    run_sql_with_exceptions(
        AI_EVENTS_MV_SQL(TABLE_BASE_NAME),
        node_roles=[NodeRole.AI_EVENTS],
    ),
]
