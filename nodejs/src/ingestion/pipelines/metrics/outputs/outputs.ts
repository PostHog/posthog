/**
 * Output names registered by the metrics ingestion deployment.
 */

export const METRICS_OUTPUT = 'metrics' as const
export type MetricsOutput = typeof METRICS_OUTPUT

/** Used only by the pre-framework consumer. */
export const METRICS_DLQ_OUTPUT = 'metrics_dlq' as const
export type MetricsDlqOutput = typeof METRICS_DLQ_OUTPUT

/** Metrics has no per-team retention setting. ClickHouse applies its own default only when the `retention-days` header is missing. */
export const DEFAULT_METRICS_RETENTION_DAYS = 30
