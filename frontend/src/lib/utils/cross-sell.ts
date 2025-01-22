import posthog from 'posthog-js'

import type { ProductKey } from '~/types'

export type ProductCrossSellContext = Record<string, unknown>

export enum ProductCrossSellLocation {
    TAXONOMIC_FILTER_EMPTY_STATE = 'taxonomic_filter_empty_state',
    CREATE_EXPERIMENT_FROM_FUNNEL_BUTTON = 'create_experiment_from_funnel_button',
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
