import { FEATURE_FLAGS } from 'lib/constants'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { PRODUCT_ANALYTICS_PRODUCT_TREE_NAME } from '~/../../products/product_analytics/manifest'
import { WEB_ANALYTICS_PRODUCT_TREE_NAME } from '~/../../products/web_analytics/manifest'

const EXPERIMENT_PRIORITIZED_ANALYTICS_ITEMS = [
    PRODUCT_ANALYTICS_PRODUCT_TREE_NAME,
    WEB_ANALYTICS_PRODUCT_TREE_NAME,
] as const

export const getSortOverride = (featureFlags: FeatureFlagsSet) => {
    return (a: TreeDataItem, b: TreeDataItem): number | null => {
        if (
            a.record?.category !== 'Analytics' ||
            b.record?.category !== 'Analytics' ||
            featureFlags[FEATURE_FLAGS.SIDEBAR_ANALYTICS_PRIORITIZATION] !== 'prioritized'
        ) {
            return null
        }

        const aIndex = EXPERIMENT_PRIORITIZED_ANALYTICS_ITEMS.indexOf(a.name as any)
        const bIndex = EXPERIMENT_PRIORITIZED_ANALYTICS_ITEMS.indexOf(b.name as any)

        // If both are in prioritized list, sort by their position on our priority list
        if (aIndex !== -1 && bIndex !== -1) {
            return aIndex - bIndex
        }

        // If only one is prioritized, it comes first
        if (aIndex !== -1) {
            return -1
        }
        if (bIndex !== -1) {
            return 1
        }

        // If neither is prioritized, maintain default sort (return null for fallback)
        return null
    }
}
