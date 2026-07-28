import { type FeatureFlagKey } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import type { ProductSetupStatus } from './types'

/**
 * A cheap, declarative approximation of a product's setup status, resolvable at
 * app boot from property definitions. A product declares its probe as `setupProbe`
 * in its manifest; `build-products.mjs` aggregates them into `productSetupProbes`
 * (see `~/products`), and all of them are answered by one Postgres-backed API call
 * (see `productSetupPreloadLogic`), so statuses are known before the
 * user first opens the product and the loading spinner rarely shows.
 *
 * Keep each probe's semantics in sync with the product's own detection logic
 * (e.g. `mcpAnalyticsOnboardingLogic`) — the product logic stays the in-scene
 * source of truth and its fresher result always wins over the preload.
 */
export interface ProductSetupProbe {
    productKey: ProductKey
    /** Any of these event property definitions existing means the product has real data. */
    hasDataProperties: string[]
    /** Any of these existing (without `hasDataProperties`) means instrumented but no traffic yet. */
    waitingProperties?: string[]
    /** Only probe when this flag is enabled. */
    featureFlag?: FeatureFlagKey
}

export function statusFromProbeDefinitions(probe: ProductSetupProbe, propertyNames: Set<string>): ProductSetupStatus {
    if (probe.hasDataProperties.some((property) => propertyNames.has(property))) {
        return 'has-data'
    }

    if (probe.waitingProperties?.some((property) => propertyNames.has(property))) {
        return 'waiting-for-data'
    }

    return 'needs-setup'
}
