/**
 * Output names registered by the metrics ingestion deployment.
 */

export const METRICS_OUTPUT = 'metrics' as const
export type MetricsOutput = typeof METRICS_OUTPUT

export const METRICS_DLQ_OUTPUT = 'metrics_dlq' as const
export type MetricsDlqOutput = typeof METRICS_DLQ_OUTPUT
