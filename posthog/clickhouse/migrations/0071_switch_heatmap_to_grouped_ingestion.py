from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.heatmaps.sql_two import KAFKA_HEATMAPS_TWO_TABLE_SQL, HEATMAPS_TABLE_TWO_MV_SQL

operations = [
    # we don't delete the old kafka and mv tables yet
    # since we want to be able to switch this in and out
    # in case it doesn't work the way we expect
    run_sql_with_exceptions(KAFKA_HEATMAPS_TWO_TABLE_SQL()),
    run_sql_with_exceptions(HEATMAPS_TABLE_TWO_MV_SQL()),
]
