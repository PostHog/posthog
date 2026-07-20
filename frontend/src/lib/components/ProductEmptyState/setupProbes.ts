import { FEATURE_FLAGS, type FeatureFlagKey } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import type { ProductSetupStatus } from './types'

/**
 * A cheap, declarative approximation of a product's setup status, resolvable at
 * app boot from event counts alone. All registered probes are answered by ONE
 * combined ClickHouse count query (see `productSetupPreloadLogic`), so statuses
 * are known before the user first opens the product and the loading spinner
 * rarely shows.
 *
 * Keep each entry's semantics in sync with the product's own detection logic
 * (e.g. `mcpAnalyticsOnboardingLogic`) — the product logic stays the in-scene
 * source of truth and its fresher result always wins over the preload.
 */
export interface ProductSetupProbe {
    productKey: ProductKey
    /** Any of these events existing means the product has real data. */
    hasDataEvents: string[]
    /** Any of these existing (without `hasDataEvents`) means instrumented but no traffic yet. */
    waitingEvents?: string[]
    /** Only probe when this flag is enabled — mirror the scene gate's `featureFlag`. */
    featureFlag?: FeatureFlagKey
}

export const PRODUCT_SETUP_PROBES: ProductSetupProbe[] = [
    {
        productKey: ProductKey.MCP_ANALYTICS,
        hasDataEvents: ['$mcp_tool_call'],
        waitingEvents: ['$mcp_initialize'],
        featureFlag: FEATURE_FLAGS.MCP_ANALYTICS,
    },
]

export function statusFromProbeCounts(
    probe: ProductSetupProbe,
    countsByEvent: Record<string, number>
): ProductSetupStatus {
    if (probe.hasDataEvents.some((event) => (countsByEvent[event] ?? 0) > 0)) {
        return 'has-data'
    }

    if (probe.waitingEvents?.some((event) => (countsByEvent[event] ?? 0) > 0)) {
        return 'waiting-for-data'
    }

    return 'needs-setup'
}
