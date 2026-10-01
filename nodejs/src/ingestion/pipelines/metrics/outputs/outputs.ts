/**
 * Output names registered by the metrics ingestion deployment. The DLQ uses
 * the framework's shared `DLQ_OUTPUT` name from `~/common/outputs`.
 */

export const METRICS_OUTPUT = 'metrics' as const
export type MetricsOutput = typeof METRICS_OUTPUT

/** Retention stamped on every produced batch; metrics has no per-team setting yet. ClickHouse falls back to `DEFAULT_RETENTION_DAYS` in `posthog/clickhouse/metrics/metrics2.py` only when this header is absent. */
export const DEFAULT_METRICS_RETENTION_DAYS = 30
