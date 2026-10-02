from django.conf import settings

TABLE_NAME = "logs34"


def LOGS34_TO_VOLUME_BUCKETS_MV_SELECT():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    # Groups rows exactly like _rollup_sql in
    # products/logs/backend/temporal/volume_tick/aggregation.py, which carries
    # the reasoning for the environment fallback and severity lowercasing;
    # `retention_days` is a measure folded into each group, not a dimension.
    # The 300s grid literal is frozen into the DDL at migration time;
    # BUCKET_SECONDS there must stay equal to it or the detector reads buckets
    # this MV never writes.
    #
    # `retention_days` rounds the lifetime from the bucket to the raw expiry up
    # to whole days, so event-time skew and bucket rounding cannot expire the
    # rollup before its logs. Microseconds preserve fractional-second expiries.
    # The 3650-day guard sits above the product's retention ceiling and bounds
    # corrupt expiries. Max keeps mixed retentions as long as the latest expiry.
    return f"""SELECT
    team_id,
    time_bucket,
    service_name,
    namespace,
    environment,
    severity_text,
    maxSimpleState(retention_days) AS retention_days,
    sumSimpleState(1) AS log_count
FROM
(
    SELECT
        team_id,
        toStartOfInterval(timestamp, toIntervalSecond(300), 'UTC') AS time_bucket,
        service_name,
        if(
            resource_attributes['k8s.namespace.name'] != '',
            resource_attributes['k8s.namespace.name'],
            resource_attributes['service.namespace']
        ) AS namespace,
        if(
            resource_attributes['deployment.environment.name'] != '',
            resource_attributes['deployment.environment.name'],
            if(
                resource_attributes['deployment.environment'] != '',
                resource_attributes['deployment.environment'],
                resource_attributes['env']
            )
        ) AS environment,
        lower(severity_text) AS severity_text,
        toUInt16(least(intDiv(greatest(dateDiff('microsecond', time_bucket, original_expiry_timestamp), 0) + 86399999999, 86400000000), 3650)) AS retention_days
    FROM {db}.{TABLE_NAME}
)
GROUP BY team_id, time_bucket, service_name, namespace, environment, severity_text"""


def LOGS34_TO_VOLUME_BUCKETS_MV():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.logs34_to_volume_buckets TO {db}.logs_volume_buckets
(
    `team_id` Int32,
    `time_bucket` DateTime('UTC'),
    `service_name` LowCardinality(String),
    `namespace` LowCardinality(String),
    `environment` LowCardinality(String),
    `severity_text` LowCardinality(String),
    `retention_days` SimpleAggregateFunction(max, UInt16),
    `log_count` SimpleAggregateFunction(sum, UInt64)
)
AS {LOGS34_TO_VOLUME_BUCKETS_MV_SELECT()}
"""
