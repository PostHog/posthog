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

export const HOG_INVOCATION_RESULTS_OUTPUT = 'hog_invocation_results' as const
export type HogInvocationResultsOutput = typeof HOG_INVOCATION_RESULTS_OUTPUT

// Producer names
//
// A producer name is a named Kafka *connection slot*, not a fixed cluster. The code
// declares which slots exist; each pipeline's Helm charts decide which Kafka cluster a
// slot connects to (broker list + security protocol) and which outputs route through it.
//
// The same slot can therefore point at different clusters in different pipelines — e.g.
// today WARPSTREAM is the warpstream-ingestion cluster for the analytics family but the
// warpstream-replay cluster for session replay. Treat these as slots, not clusters.
//
// The slot → cluster mapping (the infra side) is documented in the charts repo:
// shared/ingestion/common*.yaml and argocd/ingestion/config/*.yaml.
//
// Consolidation in progress: the legacy DEFAULT/WARPSTREAM/INGESTION slots are being
// replaced by cluster-accurate slots, so each name means exactly one cluster fleet-wide:
//   INGESTION_UPSTREAM   — dedicated ingestion cluster; re-consumed topics (overflow/async/dlq)
//   INGESTION_DOWNSTREAM — warpstream-ingestion cluster; ClickHouse-bound outputs
// DEFAULT is being retired (redundant with INGESTION_DOWNSTREAM). Pipeline-specific slots
// (e.g. session replay's warpstream-replay producer) are defined in their own module, not here.

/**
 * DEFAULT uses the existing KAFKA_PRODUCER_* env vars — backwards compatible
 * with all existing deployments including dev and hobby.
 */
export const DEFAULT_PRODUCER = 'DEFAULT' as const
export type DefaultProducer = typeof DEFAULT_PRODUCER

export const WARPSTREAM_PRODUCER = 'WARPSTREAM' as const
export type WarpstreamProducer = typeof WARPSTREAM_PRODUCER

/**
 * INGESTION targets the dedicated Kafka cluster for topics between capture and
 * ingestion — used for overflow, DLQ, and async topics.
 */
export const INGESTION_PRODUCER = 'INGESTION' as const
export type IngestionProducer = typeof INGESTION_PRODUCER

/** UPSTREAM — dedicated ingestion cluster; re-consumed topics (overflow/async/dlq). */
export const INGESTION_UPSTREAM_PRODUCER = 'INGESTION_UPSTREAM' as const
export type IngestionUpstreamProducer = typeof INGESTION_UPSTREAM_PRODUCER

/** DOWNSTREAM — warpstream-ingestion cluster; ClickHouse-bound outputs. */
export const INGESTION_DOWNSTREAM_PRODUCER = 'INGESTION_DOWNSTREAM' as const
export type IngestionDownstreamProducer = typeof INGESTION_DOWNSTREAM_PRODUCER

/** Union of all known producer names. Extend this as new producers are added. */
export type ProducerName =
    | DefaultProducer
    | WarpstreamProducer
    | IngestionProducer
    | IngestionUpstreamProducer
    | IngestionDownstreamProducer
