from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.usage_report_events_preagg.sql import (
    DISTRIBUTED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE_SQL,
    DISTRIBUTED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE_SQL,
    DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE_SQL,
    DROP_LEGACY_DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    DROP_LEGACY_KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    DROP_LEGACY_SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    DROP_LEGACY_USAGE_REPORT_EVENTS_PREAGG_MV_SQL,
    DROP_LEGACY_WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    SHARDED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE_SQL,
    SHARDED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE_SQL,
    SHARDED_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        DROP_LEGACY_USAGE_REPORT_EVENTS_PREAGG_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        DROP_LEGACY_KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        DROP_LEGACY_WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        DROP_LEGACY_DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DROP_LEGACY_SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        SHARDED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        SHARDED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        SHARDED_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
