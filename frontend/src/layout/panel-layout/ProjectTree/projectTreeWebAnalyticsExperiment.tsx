import { FEATURE_FLAGS } from 'lib/constants'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

const EXPERIMENT_PRIORITIZED_ANALYTICS_ITEMS: Record<string, string[]> = {
    prioritized: ['Product analytics', 'Web analytics'],
    prioritized_web_first: ['Web analytics', 'Product analytics'],
}

export const getSortOverride = (
    featureFlags: FeatureFlagsSet
): ((a: TreeDataItem, b: TreeDataItem) => number | null) | undefined => {
    const flagValue = featureFlags[FEATURE_FLAGS.SIDEBAR_ANALYTICS_PRIORITIZATION]

    // Early return if experiment is not enabled
    if (!flagValue || typeof flagValue !== 'string' || !(flagValue in EXPERIMENT_PRIORITIZED_ANALYTICS_ITEMS)) {
        return undefined
    }

    const prioritizedItems = EXPERIMENT_PRIORITIZED_ANALYTICS_ITEMS[flagValue]

    return (a: TreeDataItem, b: TreeDataItem): number | null => {
        // Only apply custom sorting to Analytics category items
        if (a.record?.category !== 'Analytics' || b.record?.category !== 'Analytics') {
            return null
        }

        const aIndex = prioritizedItems.indexOf(a.name)
        const bIndex = prioritizedItems.indexOf(b.name)

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
