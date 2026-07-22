import type { MetricAttributes } from 'posthog-js'
import posthog from 'posthog-js'

/**
 * Operational metrics into the PostHog Metrics product via the SDK's aggregated
 * `posthog.metrics` API (samples are batched to one data point per series every 10s).
 *
 * Attributes must stay low-cardinality: no user ids, session ids, or URLs. Every distinct
 * attribute combination is its own series, and no user or session context is attached.
 *
 * Both helpers are hard no-ops when the loaded posthog-js build doesn't ship the metrics
 * extension, and they swallow errors so telemetry can never break product code.
 */

export function metricCount(name: string, value: number = 1, attributes?: MetricAttributes): void {
    try {
        posthog.metrics?.count(name, value, attributes ? { attributes } : undefined)
    } catch {
        // never let telemetry break the product
    }
}

export function metricHistogram(name: string, value: number, unit: string, attributes?: MetricAttributes): void {
    try {
        posthog.metrics?.histogram(name, value, { unit, ...(attributes ? { attributes } : {}) })
    } catch {
        // never let telemetry break the product
    }
}
