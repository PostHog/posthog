from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.heatmaps.sql import (
    HEATMAPS_TABLE_MV_SQL,
    KAFKA_HEATMAPS_TABLE_SQL,
    HEATMAPS_TABLE_SQL,
    DISTRIBUTED_HEATMAPS_TABLE_SQL,
    WRITABLE_HEATMAPS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(WRITABLE_HEATMAPS_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_HEATMAPS_TABLE_SQL()),
    run_sql_with_exceptions(HEATMAPS_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_HEATMAPS_TABLE_SQL()),
    run_sql_with_exceptions(HEATMAPS_TABLE_MV_SQL()),
]
