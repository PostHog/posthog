from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    METRICS2_INPUT_TO_METRICS4_ATTRIBUTES_MV,
    METRICS2_INPUT_TO_METRICS4_NAMES_MV,
    METRICS2_INPUT_TO_METRICS4_RESOURCE_ATTRIBUTES_MV,
    METRICS2_INPUT_TO_METRICS4_SAMPLES_MV,
    METRICS2_INPUT_TO_METRICS4_SERIES_MV,
    METRICS4_ATTRIBUTES_TABLE_SQL,
    METRICS4_NAMES_TABLE_SQL,
    METRICS4_SAMPLES_TABLE_SQL,
    METRICS4_SERIES_TABLE_SQL,
)
from posthog.clickhouse.metrics.metrics2 import KAFKA_METRICS_AVRO2_MV_SELECT

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

operations = [
    run_sql_with_exceptions(METRICS4_SAMPLES_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS4_SERIES_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS4_NAMES_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS4_ATTRIBUTES_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRICS4_SAMPLES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRICS4_SERIES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRICS4_NAMES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRICS4_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRICS4_RESOURCE_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    # Use the sample timestamp so a late sample expires with its series.
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.kafka_metrics_avro2_mv MODIFY QUERY\n{KAFKA_METRICS_AVRO2_MV_SELECT()}",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
