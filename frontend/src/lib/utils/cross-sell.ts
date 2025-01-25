import posthog from 'posthog-js'

import type { ProductKey } from '~/types'

export type ProductCrossSellContext = Record<string, unknown>

export enum ProductCrossSellLocation {
    TAXONOMIC_FILTER_EMPTY_STATE = 'taxonomic_filter_empty_state',
    WEB_ANALYTICS_INSIGHT = 'web_analytics_insight',
}

export type ProductCrossSellProperties = {
    from: ProductKey
    to: ProductKey
    location: ProductCrossSellLocation
    context?: ProductCrossSellContext
}

export function trackProductCrossSell(properties: ProductCrossSellProperties): void {
    posthog.capture('product cross sell interaction', properties)
}
