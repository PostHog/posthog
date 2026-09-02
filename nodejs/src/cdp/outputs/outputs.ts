/**
 * Output names registered by the CDP deployments.
 *
 * Shared names (`APP_METRICS_OUTPUT`, `LOG_ENTRIES_OUTPUT`) live in
 * `common/outputs` and are re-used by the CDP monitoring path.
 * Names declared here are CDP-local — the topic each one resolves to is
 * driven by the registry build in `registry.ts`.
 */

export const WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT = 'warehouse_source_webhooks' as const
export type WarehouseSourceWebhooksOutput = typeof WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT
