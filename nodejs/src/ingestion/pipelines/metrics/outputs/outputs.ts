/**
 * Output names registered by the metrics ingestion deployment. The DLQ uses
 * the framework's shared `DLQ_OUTPUT` name from `~/common/outputs`.
 */

export const METRICS_OUTPUT = 'metrics' as const
export type MetricsOutput = typeof METRICS_OUTPUT
