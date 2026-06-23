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

// Producer names
//
// A producer name is a named Kafka connection slot, not a fixed cluster: the code declares the
// slots, and each pipeline's Helm charts wire a slot to a concrete cluster (broker list +
// security protocol) and route its outputs to it. A slot can map to different clusters in
// different pipelines. The slot → cluster mapping lives in the charts repo
// (shared/ingestion/common*.yaml, argocd/ingestion/config/*.yaml).
//
// Cluster-accurate slots:
//   INGESTION_UPSTREAM   — dedicated ingestion cluster; re-consumed topics (overflow/async/dlq)
//   INGESTION_DOWNSTREAM — warpstream-ingestion cluster; ClickHouse-bound outputs
// Pipeline-specific slots (e.g. session replay's warpstream-replay producer) live in their own module.

/** UPSTREAM — dedicated ingestion cluster; re-consumed topics (overflow/async/dlq). */
export const INGESTION_UPSTREAM_PRODUCER = 'INGESTION_UPSTREAM' as const
export type IngestionUpstreamProducer = typeof INGESTION_UPSTREAM_PRODUCER

/** DOWNSTREAM — warpstream-ingestion cluster; ClickHouse-bound outputs. */
export const INGESTION_DOWNSTREAM_PRODUCER = 'INGESTION_DOWNSTREAM' as const
export type IngestionDownstreamProducer = typeof INGESTION_DOWNSTREAM_PRODUCER

/** Union of all known producer names. Extend this as new producers are added. */
export type ProducerName = IngestionUpstreamProducer | IngestionDownstreamProducer
