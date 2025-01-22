import api from 'lib/api'

import type { ProductKey, TeamType } from '~/types'

export enum ProductIntentContext {
    // Cross Sell
    CROSS_SELL = 'cross sell',

    // Onboarding
    ONBOARDING_PRODUCT_SELECTED_PRIMARY = 'onboarding product selected - primary',
    ONBOARDING_PRODUCT_SELECTED_SECONDARY = 'onboarding product selected - secondary',

    // Data Warehouse
    SELECTED_CONNECTOR = 'selected connector',

    // Experiments
    EXPERIMENT_CREATED = 'experiment created',

    // Feature Flags
    FEATURE_FLAG_CREATED = 'feature flag created',
}

export type ProductIntentProperties = {
    product_type: ProductKey
    intent_context: ProductIntentContext
    metadata?: Record<string, unknown>
}

export function addProductIntent(properties: ProductIntentProperties): Promise<TeamType> {
    return api.productIntents.update(properties)
}

export type ProductCrossSellMetadata = Record<string, unknown>

export enum ProductCrossSellLocation {
    TAXONOMIC_FILTER_EMPTY_STATE = 'taxonomic_filter_empty_state',
}

export type ProductCrossSellProperties = {
    from: ProductKey
    to: ProductKey
    location: ProductCrossSellLocation
    metadata?: ProductCrossSellMetadata
}

export function addProductCrossSell(properties: ProductCrossSellProperties): Promise<TeamType> {
    return api.productIntents.update({
        product_type: properties.to,
        intent_context: ProductIntentContext.CROSS_SELL,
        metadata: {
            ...properties.metadata,
            from: properties.from,
            to: properties.to,
            location: properties.location,
        },
    })
}
