"""ClickHouse schema for the FinOps `usage_meters` pipeline (usage side only — no dollars).

Product/platform services emit dimensionless usage meters ("team X pushed N events
through consumer Y", "activity Z ran M CPU-seconds") onto a dedicated Kafka topic; a
Kafka-engine table + materialized view land them in a replicated table on the OPS cluster —
PostHog's internal ops/observability cluster (home of `query_log_archive`) — deliberately off
the customer-facing analytics path.

Pricing is a separate pipeline: a vendor-bill importer lands cost totals, and one
allocation job joins usage share × bill to write the priced `cost_attribution` table.
Nothing here writes dollars — see docs/internal/finops-attribution-implementation.md.

Uses the ingestion-layer Kafka pattern of `usage_report_events_preagg`, but lands on the
single-shard OPS cluster (replicated, not sharded — like `query_log_archive`) because usage
meters are internal ops telemetry, not product data.
"""

from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_FINOPS_USAGE_METERS, kafka_engine
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_FINOPS_USAGE_METERS

FINOPS_USAGE_METERS_TABLE = "finops_usage_meters"
SHARDED_FINOPS_USAGE_METERS_TABLE = f"sharded_{FINOPS_USAGE_METERS_TABLE}"
WRITABLE_FINOPS_USAGE_METERS_TABLE = f"writable_{FINOPS_USAGE_METERS_TABLE}"
KAFKA_FINOPS_USAGE_METERS_TABLE = f"kafka_{FINOPS_USAGE_METERS_TABLE}"
FINOPS_USAGE_METERS_MV = f"{FINOPS_USAGE_METERS_TABLE}_mv"

# Meters are consumed by the allocation job for the period, then disposable. A short TTL
# keeps this table small; raise it only if late-arriving vendor bills need a longer window.
FINOPS_USAGE_METERS_TTL_DAYS = 90

# The frozen wire contract: the emitter (a later PR) produces one JSON object per aggregated
# meter with exactly these field names. `product`/`team_id`/`org_id`/`feature`/`environment`
# are the ambient attribution inherited at the chokepoint; the rest describe the usage itself.
FINOPS_USAGE_METERS_COLUMNS = """
    timestamp DateTime64(6, 'UTC'),
    product LowCardinality(String),
    team_id Int64,
    org_id String,
    feature LowCardinality(String),
    environment LowCardinality(String),
    billable_unit LowCardinality(String),
    quantity Float64,
    system LowCardinality(String),
    workload String,
    resource_id String,
    duration_ms Float64,
    service_name LowCardinality(String),
    count UInt64
""".strip()


def SHARDED_FINOPS_USAGE_METERS_TABLE_SQL() -> str:
    # OPS is a single-shard (1xN) cluster: the data table is replicated, not sharded.
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_FINOPS_USAGE_METERS_TABLE}
(
    {FINOPS_USAGE_METERS_COLUMNS}
)
ENGINE = {MergeTreeEngine(SHARDED_FINOPS_USAGE_METERS_TABLE, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (environment, product, team_id, billable_unit, timestamp)
TTL toDate(timestamp) + INTERVAL {FINOPS_USAGE_METERS_TTL_DAYS} DAY
SETTINGS ttl_only_drop_parts = 1
"""


def DISTRIBUTED_FINOPS_USAGE_METERS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {FINOPS_USAGE_METERS_TABLE}
(
    {FINOPS_USAGE_METERS_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_FINOPS_USAGE_METERS_TABLE,
            cluster=settings.CLICKHOUSE_OPS_CLUSTER,
        )
    }
"""


def WRITABLE_FINOPS_USAGE_METERS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {WRITABLE_FINOPS_USAGE_METERS_TABLE}
(
    {FINOPS_USAGE_METERS_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_FINOPS_USAGE_METERS_TABLE,
            cluster=settings.CLICKHOUSE_OPS_CLUSTER,
        )
    }
"""


def KAFKA_FINOPS_USAGE_METERS_TABLE_SQL() -> str:
    # Consumes from the shared WarpStream virtual cluster. This is a brand-new topic with no
    # MSK counterpart, so — unlike the MSK→WS cutover tables (migration 0247) — there is only
    # ever this one Kafka table, and no cloud-guard against double-consumption is needed.
    return f"""
CREATE TABLE IF NOT EXISTS {KAFKA_FINOPS_USAGE_METERS_TABLE}
(
    {FINOPS_USAGE_METERS_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_CLICKHOUSE_FINOPS_USAGE_METERS,
            group=CONSUMER_GROUP_FINOPS_USAGE_METERS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_SHARED_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_num_consumers = 1
"""


def FINOPS_USAGE_METERS_MV_SQL() -> str:
    # Straight projection: the emitter already produces flat, typed fields (unlike the
    # events pipeline's JSON blob), so the MV just forwards them to the writable table.
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {FINOPS_USAGE_METERS_MV}
TO {WRITABLE_FINOPS_USAGE_METERS_TABLE}
AS SELECT
    timestamp,
    product,
    team_id,
    org_id,
    feature,
    environment,
    billable_unit,
    quantity,
    system,
    workload,
    resource_id,
    duration_ms,
    service_name,
    count
FROM {KAFKA_FINOPS_USAGE_METERS_TABLE}
"""
