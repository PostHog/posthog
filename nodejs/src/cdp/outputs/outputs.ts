/**
 * Output names registered by the CDP deployments.
 *
 * Shared names (`APP_METRICS_OUTPUT`, `LOG_ENTRIES_OUTPUT`) live in
 * `ingestion/common/outputs` and are re-used by the CDP monitoring path.
 * Names declared here are CDP-local — the topic each one resolves to is
 * driven by the registry build in `registry.ts`.
 */

export const PREFILTERED_EVENTS_OUTPUT = 'prefiltered_events' as const
export type PrefilteredEventsOutput = typeof PREFILTERED_EVENTS_OUTPUT

export const PRECALCULATED_PERSON_PROPERTIES_OUTPUT = 'precalculated_person_properties' as const
export type PrecalculatedPersonPropertiesOutput = typeof PRECALCULATED_PERSON_PROPERTIES_OUTPUT

export const BATCH_HOGFLOW_REQUESTS_OUTPUT = 'batch_hogflow_requests' as const
export type BatchHogflowRequestsOutput = typeof BATCH_HOGFLOW_REQUESTS_OUTPUT

export const WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT = 'warehouse_source_webhooks' as const
export type WarehouseSourceWebhooksOutput = typeof WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT
