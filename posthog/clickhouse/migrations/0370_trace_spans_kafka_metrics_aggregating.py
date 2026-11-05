from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.traces import TRACE_SPANS_KAFKA_METRICS_TABLE_SQL, TRACE_SPANS_TO_KAFKA_METRICS_MV

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The table declared max columns but a plain MergeTree engine, so it kept one row per insert block and
# never collapsed them. It is recreated as an AggregatingMergeTree, like logs_kafka_metrics and
# metrics_kafka_metrics. Its rows are only consumer-lag bookkeeping, so dropping them loses nothing.
#
# The MV on `trace_spans` writes into the table, so it goes first and comes back last: an MV whose
# target is missing would fail every span insert. Spans written in between have no lag rows, which
# the next block corrects. The table is replicated, so its drop waits with SYNC before the CREATE.
operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.trace_spans_to_kafka_metrics_mv", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.trace_spans_kafka_metrics SYNC", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_SPANS_KAFKA_METRICS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_SPANS_TO_KAFKA_METRICS_MV(), node_roles=[NodeRole.LOGS]),
]
