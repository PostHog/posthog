import { useValues } from 'kea'
import { ComponentType, Suspense } from 'react'

import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { ProductItemCategory } from '~/queries/schema/schema-general'

export type CategorySuffixNav = 'classic' | 'today'

interface CategorySuffix {
    flag: FeatureFlagKey
    suffix: Record<CategorySuffixNav, ComponentType>
}

const customCategorySuffixRegistry: Partial<Record<string, CategorySuffix>> = {
    [ProductItemCategory.MESSAGING]: {
        flag: FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR,
        suffix: {
            classic: lazyWithRetry(() =>
                import('products/workflows/frontend/AdventCalendar/entry/AdventNavTreeButton').then((module) => ({
                    default: module.AdventNavTreeButton,
                }))
            ),
            today: lazyWithRetry(() =>
                import('products/workflows/frontend/AdventCalendar/entry/AdventTodayNavTreeButton').then((module) => ({
                    default: module.AdventTodayNavTreeButton,
                }))
            ),
        },
    },
}

export function CustomCategorySuffix({
    category,
    nav,
}: {
    category: string
    nav: CategorySuffixNav
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const entry = customCategorySuffixRegistry[category]
    if (!entry || !featureFlags[entry.flag]) {
        return null
    }
    const Suffix = entry.suffix[nav]
    return (
        <Suspense fallback={null}>
            <Suffix />
        </Suspense>
    )
}
