/**
 * Output names registered by the metrics ingestion deployment. The framework
 * pipeline consumer uses the shared `DLQ_OUTPUT` name from `~/common/outputs`.
 */

export const METRICS_OUTPUT = 'metrics' as const
export type MetricsOutput = typeof METRICS_OUTPUT

/** DLQ name of the pre-framework consumer. Remove it with that consumer. */
export const METRICS_DLQ_OUTPUT = 'metrics_dlq' as const
export type MetricsDlqOutput = typeof METRICS_DLQ_OUTPUT

/** Retention stamped on every produced batch; metrics has no per-team setting yet. ClickHouse falls back to `DEFAULT_RETENTION_DAYS` in `posthog/clickhouse/metrics/metrics2.py` only when this header is absent. */
export const DEFAULT_METRICS_RETENTION_DAYS = 30
