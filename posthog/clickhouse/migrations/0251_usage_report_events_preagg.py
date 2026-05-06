from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.usage_report_events_preagg.sql import (
    DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    KAFKA_USAGE_REPORT_EVENTS_PREAGG_WS_TABLE_SQL,
    SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    USAGE_REPORT_EVENTS_PREAGG_MV_SQL,
    USAGE_REPORT_EVENTS_PREAGG_WS_MV_SQL,
    WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
)

operations = [
    # 1. Sharded data table on the main cluster (data nodes only).
    run_sql_with_exceptions(
        SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
    ),
    # 2. Distributed read view on data nodes (queries fan out from here).
    run_sql_with_exceptions(
        DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # 3. Writable distributed table on ingestion nodes — the MVs write here,
    #    and rows are routed to the right shard by sipHash64(team_id).
    run_sql_with_exceptions(
        WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 4. Dedicated Kafka engine table for MSK — own consumer group keeps
    #    this aggregate off the main events ingestion's offset stream.
    run_sql_with_exceptions(
        KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 5. Dedicated Kafka engine table for WarpStream.
    run_sql_with_exceptions(
        KAFKA_USAGE_REPORT_EVENTS_PREAGG_WS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 6. MV reading from the dedicated MSK Kafka table.
    run_sql_with_exceptions(
        USAGE_REPORT_EVENTS_PREAGG_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 7. MV reading from the dedicated WarpStream Kafka table.
    run_sql_with_exceptions(
        USAGE_REPORT_EVENTS_PREAGG_WS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
