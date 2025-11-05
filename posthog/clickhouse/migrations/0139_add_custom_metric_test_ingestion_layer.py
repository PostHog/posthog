from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.custom_metrics import CUSTOM_METRICS_INGESTION_LAYER_VIEW, CUSTOM_METRICS_TEST_VIEW

operations = [
    run_sql_with_exceptions(
        CUSTOM_METRICS_TEST_VIEW(),
        node_roles=[NodeRole.INGESTION_EVENTS, NodeRole.SHUFFLEHOG],
    ),
    run_sql_with_exceptions(
        CUSTOM_METRICS_INGESTION_LAYER_VIEW(),
        node_roles=[NodeRole.INGESTION_EVENTS, NodeRole.SHUFFLEHOG],
    ),
]
