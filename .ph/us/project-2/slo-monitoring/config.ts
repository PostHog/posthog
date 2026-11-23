import { analyticsPlatform } from '../shared/teams'

export const team = analyticsPlatform

export interface SloOperation {
    // The `properties.operation` value of the slo_operation_started and slo_operation_completed events (see posthog/slo/types.py).
    key: string
    name: string
    slo: number
    regions: string[]
}

// Add an operation here to get its burn rate and duration insights and its dashboard section.
export const operations: SloOperation[] = [
    { key: 'export', name: 'Exports', slo: 99.95, regions: ['US', 'EU'] },
    { key: 'subscription_delivery', name: 'Subscription deliveries', slo: 99.95, regions: ['US', 'EU'] },
    { key: 'subscription_create', name: 'Subscription created', slo: 99.95, regions: ['US', 'EU'] },
    { key: 'subscription_delete', name: 'Subscription deleted', slo: 99.95, regions: ['US', 'EU'] },
    { key: 'ai_subscription_prompt_generation', name: 'AI report generation', slo: 99.95, regions: ['US', 'EU'] },
    { key: 'alert_check', name: 'Alert checks', slo: 99.95, regions: ['US', 'EU'] },
    { key: 'alert_delivery', name: 'Alert notification delivery', slo: 99.95, regions: ['US', 'EU'] },
    { key: 'dashboard_widget_delivery', name: 'Dashboard widget delivery', slo: 99.95, regions: ['US', 'EU'] },
    // Sampled at 1% (QUERY_SERVICE_SLO_SAMPLE_RATE in posthog/settings/web.py). The queries weight each event by 1/properties.sample_rate, so nothing here depends on the rate.
    { key: 'query_service', name: 'Query service', slo: 99.95, regions: ['US', 'EU'] },
]

const byKey = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0)

// The dashboard sections, the success rate query and the region rows all go in key order.
export const sortedOperations = [...operations].sort((a, b) => byKey(a.key, b.key))

export function sortedRegions(operation: SloOperation): string[] {
    return [...operation.regions].sort(byKey)
}

export const tags = ['managed-by:terraform', 'slo']
