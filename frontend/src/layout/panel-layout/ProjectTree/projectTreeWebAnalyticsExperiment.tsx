import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { FileSystemImport } from '~/queries/schema/schema-general'

import { getDefaultTreeProducts } from './defaultTree'

const EXPERIMENT_ANALYTICS_VISUAL_ORDER: Record<string, Record<string, number>> = {
    prioritized: {
        'Product analytics': 10,
        'Web analytics': 20,
    },
    prioritized_web_first: {
        'Web analytics': 10,
        'Product analytics': 20,
    },
}

export const getExperimentalProductsTree = (featureFlags: FeatureFlagsSet): FileSystemImport[] | null => {
    const flagValue = featureFlags[FEATURE_FLAGS.SIDEBAR_ANALYTICS_PRIORITIZATION]

    // Early return if experiment is not enabled
    if (!flagValue || typeof flagValue !== 'string' || !(flagValue in EXPERIMENT_ANALYTICS_VISUAL_ORDER)) {
        return null
    }

    const visualOrders = EXPERIMENT_ANALYTICS_VISUAL_ORDER[flagValue]
    const products = getDefaultTreeProducts()

    // Override visualOrder for analytics items based on experiment
    return products.map((product) => {
        if (product.category === 'Analytics' && product.path in visualOrders) {
            return {
                ...product,
                visualOrder: visualOrders[product.path],
            }
        }
        return product
    })
}
