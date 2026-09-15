-- Read metrics3-backfill.md before running these statements.
-- Use the same fixed, half-open time range for all three inserts.
-- Keep ingestion and the existing materialized views running.

-- 1. Restore series within each original expiry day.
INSERT INTO posthog.metric_series3
(
    team_id, metric_name, series_fingerprint, metric_type, unit,
    aggregation_temporality, is_monotonic, service_name,
    instrumentation_scope, resource_attributes, attributes,
    last_seen, original_expiry_timestamp
)
WITH
    labels AS
    (
        SELECT
            team_id, metric_name, series_fingerprint,
            argMax(tuple(resource_attributes, attributes), last_seen) AS maps
        FROM posthog.metric_series2
        GROUP BY team_id, metric_name, series_fingerprint
    ),
    samples AS
    (
        SELECT
            team_id, metric_name, series_fingerprint,
            argMax(
                tuple(metric_type, unit, aggregation_temporality, is_monotonic,
                      service_name, instrumentation_scope, timestamp, original_expiry_timestamp),
                timestamp
            ) AS sample
        FROM posthog.metrics2
        WHERE has_labels
          AND timestamp >= {batch_start:DateTime64(6, 'UTC')}
          AND timestamp < {batch_end:DateTime64(6, 'UTC')}
          AND original_expiry_timestamp > now64(6)
        GROUP BY team_id, metric_name, series_fingerprint, toDate(original_expiry_timestamp)
    )
SELECT
    samples.team_id, samples.metric_name, samples.series_fingerprint,
    sample.1, sample.2, sample.3, sample.4, sample.5, sample.6,
    maps.1, maps.2, sample.7, sample.8
FROM samples
INNER JOIN labels USING (team_id, metric_name, series_fingerprint)
SETTINGS max_threads = 2;

-- 2. Restore metric names, including samples with empty label maps.
INSERT INTO posthog.metric_names3
(
    team_id, metric_name, time_bucket,
    original_expiry_time_bucket, original_expiry_timestamp
)
SELECT
    team_id,
    metric_name,
    toStartOfHour(timestamp) AS time_bucket,
    toStartOfHour(metrics2.original_expiry_timestamp) AS original_expiry_time_bucket,
    max(metrics2.original_expiry_timestamp) AS original_expiry_timestamp
FROM posthog.metrics2
WHERE has_labels
  AND timestamp >= {batch_start:DateTime64(6, 'UTC')}
  AND timestamp < {batch_end:DateTime64(6, 'UTC')}
  AND metrics2.original_expiry_timestamp > now64(6)
GROUP BY team_id, metric_name, time_bucket, original_expiry_time_bucket
SETTINGS max_threads = 2;

-- 3. Restore metric and resource attribute counts.
-- Run this insert once per range. A repeat adds the counts again.
INSERT INTO posthog.metric_attributes3
(
    team_id, metric_name, time_bucket, original_expiry_time_bucket,
    service_name, attribute_key, attribute_value, attribute_type, attribute_count
)
WITH
    labels AS
    (
        SELECT
            team_id, metric_name, series_fingerprint,
            argMax(tuple(resource_attributes, attributes), last_seen) AS maps
        FROM posthog.metric_series2
        GROUP BY team_id, metric_name, series_fingerprint
    ),
    samples AS
    (
        SELECT
            team_id, metric_name, series_fingerprint, service_name,
            toStartOfHour(timestamp) AS time_bucket,
            toStartOfHour(original_expiry_timestamp) AS original_expiry_time_bucket,
            count() AS labelled_samples
        FROM posthog.metrics2
        WHERE has_labels
          AND timestamp >= {batch_start:DateTime64(6, 'UTC')}
          AND timestamp < {batch_end:DateTime64(6, 'UTC')}
          AND toStartOfHour(original_expiry_timestamp) > now()
        GROUP BY team_id, metric_name, series_fingerprint, service_name,
                 time_bucket, original_expiry_time_bucket
    ),
    labelled AS
    (
        SELECT
            samples.*,
            maps.1 AS resource_attributes,
            mapFilter((k, v) -> length(k) < 256 AND length(v) < 256, maps.2) AS attributes
        FROM samples
        INNER JOIN labels USING (team_id, metric_name, series_fingerprint)
    )
SELECT
    team_id, metric_name, time_bucket, original_expiry_time_bucket, service_name,
    attribute.2 AS attribute_key,
    attribute.3 AS attribute_value,
    attribute.1 AS attribute_type,
    sum(labelled_samples) AS attribute_count
FROM labelled
ARRAY JOIN arrayConcat(
    arrayMap((k, v) -> tuple('metric', k, v), mapKeys(attributes), mapValues(attributes)),
    arrayMap((k, v) -> tuple('resource', k, v), mapKeys(resource_attributes), mapValues(resource_attributes))
) AS attribute
GROUP BY team_id, metric_name, time_bucket, original_expiry_time_bucket,
         service_name, attribute_key, attribute_value, attribute_type
SETTINGS max_threads = 2;
