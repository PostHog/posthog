/**
 * Output names registered by the logs/traces ingestion deployments.
 *
 * These are deployment-local — same string `'logs'` is used by both the logs
 * and traces servers, but the topic each one resolves to differs (driven by the
 * registry build in `registry.ts`).
 */

export const LOGS_OUTPUT = 'logs' as const
export type LogsOutput = typeof LOGS_OUTPUT

export const LOGS_DLQ_OUTPUT = 'logs_dlq' as const
export type LogsDlqOutput = typeof LOGS_DLQ_OUTPUT
