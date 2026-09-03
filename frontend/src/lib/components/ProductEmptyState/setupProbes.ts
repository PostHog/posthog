import { type FeatureFlagKey } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { ProductKey } from '~/queries/schema/schema-general'

import type { ProductSetupStatus } from './types'

/**
 * A cheap, declarative approximation of a product's setup status, resolvable at
 * app boot from event definitions. A product declares its probe as `setupProbe`
 * in its manifest; `build-products.mjs` aggregates them into `productSetupProbes`
 * (see `~/products`), and each one is answered by a Postgres-backed API call
 * (see `productSetupPreloadLogic`), so statuses are known before the
 * user first opens the product and the loading spinner rarely shows.
 *
 * Keep each probe's semantics in sync with the product's own detection logic
 * (e.g. `mcpAnalyticsOnboardingLogic`) — the product logic stays the in-scene
 * source of truth and its fresher result always wins over the preload.
 */
export interface ProductSetupProbe {
    productKey: ProductKey
    /** Any of these event definitions existing means the product has real data. */
    hasDataEvents: string[]
    /** Any of these existing (without `hasDataEvents`) means instrumented but no traffic yet. */
    waitingEvents?: string[]
    /**
     * Ignore definitions whose last ingested occurrence is older than this many
     * days, so a product that stopped sending long ago reads as needing setup
     * again. Definitions that were never stamped (`last_seen_at` null) count as
     * fresh. Omit to match on bare existence, for products where any history
     * means set up. Keep in sync with the staleness window the product's own
     * detection logic uses.
     */
    staleAfterDays?: number
    /** Only probe when this flag is enabled. */
    featureFlag?: FeatureFlagKey
}

/** The slice of an event definition a probe needs to answer. */
export interface ProbeEventDefinition {
    name: string
    last_seen_at?: string | null
}

export function statusFromProbeDefinitions(
    probe: ProductSetupProbe,
    definitions: ProbeEventDefinition[]
): ProductSetupStatus {
    const freshNames = new Set(
        definitions
            .filter(
                (definition) =>
                    probe.staleAfterDays === undefined ||
                    !definition.last_seen_at ||
                    // Seconds, to match the `isDefinitionStale` the products themselves use:
                    // a `has-data` published here cannot be replaced by a later `needs-setup`.
                    dayjs().diff(dayjs(definition.last_seen_at), 'second') <= probe.staleAfterDays * 24 * 60 * 60
            )
            .map((definition) => definition.name)
    )

    if (probe.hasDataEvents.some((event) => freshNames.has(event))) {
        return 'has-data'
    }

    if (probe.waitingEvents?.some((event) => freshNames.has(event))) {
        return 'waiting-for-data'
    }

    return 'needs-setup'
}
