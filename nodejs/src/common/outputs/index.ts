// Output names shared across pipelines

export * from './persons'

export const EVENTS_OUTPUT = 'events' as const
export type EventOutput = typeof EVENTS_OUTPUT

export const AI_EVENTS_OUTPUT = 'ai_events' as const
export type AiEventOutput = typeof AI_EVENTS_OUTPUT

export const ASYNC_OUTPUT = 'async' as const
export type AsyncOutput = typeof ASYNC_OUTPUT

export const INGESTION_WARNINGS_OUTPUT = 'ingestion_warnings' as const
export type IngestionWarningsOutput = typeof INGESTION_WARNINGS_OUTPUT

export const DLQ_OUTPUT = 'dlq' as const
export type DlqOutput = typeof DLQ_OUTPUT

export const OVERFLOW_OUTPUT = 'overflow' as const
export type OverflowOutput = typeof OVERFLOW_OUTPUT

export const GROUPS_OUTPUT = 'groups' as const
export type GroupsOutput = typeof GROUPS_OUTPUT

export const APP_METRICS_OUTPUT = 'app_metrics' as const
export type AppMetricsOutput = typeof APP_METRICS_OUTPUT

export const LOG_ENTRIES_OUTPUT = 'log_entries' as const
export type LogEntriesOutput = typeof LOG_ENTRIES_OUTPUT

export const TOPHOG_OUTPUT = 'tophog' as const
export type TophogOutput = typeof TOPHOG_OUTPUT

export const HOG_INVOCATION_RESULTS_OUTPUT = 'hog_invocation_results' as const
export type HogInvocationResultsOutput = typeof HOG_INVOCATION_RESULTS_OUTPUT

export const MESSAGE_ASSETS_OUTPUT = 'message_assets' as const
export type MessageAssetsOutput = typeof MESSAGE_ASSETS_OUTPUT
