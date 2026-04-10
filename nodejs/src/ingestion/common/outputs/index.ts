// Output names shared across pipelines

export const EVENTS_OUTPUT = 'events' as const
export type EventOutput = typeof EVENTS_OUTPUT

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

// Producer names

/**
 * DEFAULT uses the existing KAFKA_PRODUCER_* env vars — backwards compatible
 * with all existing deployments including dev and hobby.
 */
export const DEFAULT_PRODUCER = 'DEFAULT' as const
export type DefaultProducer = typeof DEFAULT_PRODUCER

export const WARPSTREAM_PRODUCER = 'WARPSTREAM' as const
export type WarpstreamProducer = typeof WARPSTREAM_PRODUCER

/** Union of all known producer names. Extend this as new producers are added. */
export type ProducerName = DefaultProducer | WarpstreamProducer
