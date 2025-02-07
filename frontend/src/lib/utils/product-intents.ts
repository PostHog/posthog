import api from 'lib/api'

import type { ProductKey, TeamType } from '~/types'

export enum ProductIntentContext {
    // Onboarding
    ONBOARDING_PRODUCT_SELECTED_PRIMARY = 'onboarding product selected - primary',
    ONBOARDING_PRODUCT_SELECTED_SECONDARY = 'onboarding product selected - secondary',

    // Data Warehouse
    SELECTED_CONNECTOR = 'selected connector',

    // Experiments
    EXPERIMENT_CREATED = 'experiment created',

    // Feature Flags
    FEATURE_FLAG_CREATED = 'feature flag created',

    // Cross Sells
    TAXONOMIC_FILTER_EMPTY_STATE = 'taxonomic filter empty state',
    WEB_ANALYTICS_INSIGHT = 'web_analytics_insight',
    WEB_VITALS_INSIGHT = 'web_vitals_insight',
    CREATE_EXPERIMENT_FROM_FUNNEL_BUTTON = 'create experiment from funnel button',
}

export type ProductIntentMetadata = Record<string, unknown>

export type ProductIntentProperties = {
    product_type: ProductKey
    intent_context: ProductIntentContext
    metadata?: ProductIntentMetadata
}

export function addProductIntent(properties: ProductIntentProperties): Promise<TeamType | null> {
    return api.productIntents.update(properties)
}

export type ProductCrossSellProperties = {
    from: ProductKey
    to: ProductKey
    intent_context: ProductIntentContext
    metadata?: ProductIntentMetadata
}

export function addProductIntentForCrossSell(properties: ProductCrossSellProperties): Promise<TeamType | null> {
    return api.productIntents.update({
        product_type: properties.to,
        intent_context: properties.intent_context,
        metadata: {
            ...properties.metadata,
            from: properties.from,
            to: properties.to,
            type: 'cross_sell',
        },
    })
}
