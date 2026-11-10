from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    KAFKA_METRICS4_METRICS_CLUSTER_GROUP,
    KAFKA_METRICS_AVRO4_MV,
    KAFKA_METRICS_AVRO4_TABLE_SQL,
    METRICS4_ATTRIBUTES_TABLE_SQL,
    METRICS4_INPUT_TABLE_SQL,
    METRICS4_INPUT_TO_METRICS4_ATTRIBUTES_MV,
    METRICS4_INPUT_TO_METRICS4_NAMES_MV,
    METRICS4_INPUT_TO_METRICS4_RESOURCE_ATTRIBUTES_MV,
    METRICS4_INPUT_TO_METRICS4_SAMPLES_MV,
    METRICS4_INPUT_TO_METRICS4_SERIES_MV,
    METRICS4_INPUT_TO_METRICS_KAFKA_METRICS_MV,
    METRICS4_NAMES_TABLE_SQL,
    METRICS4_SAMPLES_TABLE_SQL,
    METRICS4_SERIES_TABLE_SQL,
    METRICS4_VIEW_SQL,
    METRICS_KAFKA_METRICS_TABLE_SQL,
    WRITABLE_METRICS4_ATTRIBUTES_TABLE_SQL,
    WRITABLE_METRICS4_NAMES_TABLE_SQL,
    WRITABLE_METRICS4_SAMPLES_TABLE_SQL,
    WRITABLE_METRICS4_SERIES_TABLE_SQL,
    WRITABLE_METRICS_KAFKA_METRICS_TABLE_SQL,
)
from posthog.run_mode import run_mode

METRICS_CLUSTER = settings.CLICKHOUSE_METRICS_CLUSTER

# These match the ingestion_metrics role in the declarative schema. Dev runs smaller consumers.
KAFKA_SETTINGS = (
    {"flush_interval_ms": 3_000, "max_block_size": 10_000, "num_consumers": 4, "poll_max_batch_size": 100}
    if run_mode().region == "DEV"
    else {"num_consumers": 4}
)

# The metrics and ingestion-metrics nodes were created by hand and hold these objects already, so
# every statement is a no-op on them. This records the layout and builds it on a replaced cluster.
# The creates skip existing tables, so the column, view, codec, and sorting key changes from 0370,
# 0371, and 0372 are applied to those nodes by hand as well.
#
# The creates leave require_hosts off, so this applies cleanly before those nodes join
# posthog_migrations. Nothing here drops the logs or apm side, which keeps running until reads cut over.
#
# The Kafka MV comes last: it starts consumption, so everything it writes through has to exist first.
#
# The multinode stack keeps metrics on logs and apm, so this migration is cloud-only.
operations = (
    [
        run_sql_with_exceptions(METRICS4_SAMPLES_TABLE_SQL(storage_policy="s3_tiered"), node_roles=[NodeRole.METRICS]),
        run_sql_with_exceptions(METRICS4_SERIES_TABLE_SQL(), node_roles=[NodeRole.METRICS]),
        run_sql_with_exceptions(METRICS4_NAMES_TABLE_SQL(), node_roles=[NodeRole.METRICS]),
        run_sql_with_exceptions(METRICS4_ATTRIBUTES_TABLE_SQL(), node_roles=[NodeRole.METRICS]),
        run_sql_with_exceptions(METRICS_KAFKA_METRICS_TABLE_SQL(), node_roles=[NodeRole.METRICS]),
        run_sql_with_exceptions(METRICS4_VIEW_SQL(), node_roles=[NodeRole.METRICS]),
        run_sql_with_exceptions(
            WRITABLE_METRICS4_SAMPLES_TABLE_SQL(cluster=METRICS_CLUSTER), node_roles=[NodeRole.INGESTION_METRICS]
        ),
        run_sql_with_exceptions(
            WRITABLE_METRICS4_SERIES_TABLE_SQL(cluster=METRICS_CLUSTER), node_roles=[NodeRole.INGESTION_METRICS]
        ),
        run_sql_with_exceptions(
            WRITABLE_METRICS4_NAMES_TABLE_SQL(cluster=METRICS_CLUSTER), node_roles=[NodeRole.INGESTION_METRICS]
        ),
        run_sql_with_exceptions(
            WRITABLE_METRICS4_ATTRIBUTES_TABLE_SQL(cluster=METRICS_CLUSTER), node_roles=[NodeRole.INGESTION_METRICS]
        ),
        run_sql_with_exceptions(
            WRITABLE_METRICS_KAFKA_METRICS_TABLE_SQL(cluster=METRICS_CLUSTER), node_roles=[NodeRole.INGESTION_METRICS]
        ),
        run_sql_with_exceptions(METRICS4_INPUT_TABLE_SQL(), node_roles=[NodeRole.INGESTION_METRICS]),
        run_sql_with_exceptions(METRICS4_INPUT_TO_METRICS4_SAMPLES_MV(), node_roles=[NodeRole.INGESTION_METRICS]),
        run_sql_with_exceptions(METRICS4_INPUT_TO_METRICS4_SERIES_MV(), node_roles=[NodeRole.INGESTION_METRICS]),
        run_sql_with_exceptions(METRICS4_INPUT_TO_METRICS4_NAMES_MV(), node_roles=[NodeRole.INGESTION_METRICS]),
        run_sql_with_exceptions(METRICS4_INPUT_TO_METRICS4_ATTRIBUTES_MV(), node_roles=[NodeRole.INGESTION_METRICS]),
        run_sql_with_exceptions(
            METRICS4_INPUT_TO_METRICS4_RESOURCE_ATTRIBUTES_MV(), node_roles=[NodeRole.INGESTION_METRICS]
        ),
        run_sql_with_exceptions(METRICS4_INPUT_TO_METRICS_KAFKA_METRICS_MV(), node_roles=[NodeRole.INGESTION_METRICS]),
        run_sql_with_exceptions(
            KAFKA_METRICS_AVRO4_TABLE_SQL(group=KAFKA_METRICS4_METRICS_CLUSTER_GROUP, **KAFKA_SETTINGS),
            node_roles=[NodeRole.INGESTION_METRICS],
        ),
        run_sql_with_exceptions(KAFKA_METRICS_AVRO4_MV(), node_roles=[NodeRole.INGESTION_METRICS]),
    ]
    if run_mode().is_deployed_cloud
    else []
)
