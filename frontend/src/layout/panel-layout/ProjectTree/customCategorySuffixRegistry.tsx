import { useValues } from 'kea'
import { ComponentType, Suspense } from 'react'

import { PostHogErrorBoundary } from '@posthog/react'

import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { ProductItemCategory } from '~/queries/schema/schema-general'

export type CategorySuffixNav = 'classic' | 'today'

const AdventNavTreeButton = lazyWithRetry(() =>
    import('products/workflows/frontend/AdventCalendar/entry/AdventNavTreeButton').then((module) => ({
        default: module.AdventNavTreeButton,
    }))
)

const customCategorySuffixRegistry: Partial<
    Record<string, { flag: FeatureFlagKey; Suffix: ComponentType<{ nav: CategorySuffixNav }> }>
> = {
    [ProductItemCategory.MESSAGING]: { flag: FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR, Suffix: AdventNavTreeButton },
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
    return entry && featureFlags[entry.flag] ? (
        <PostHogErrorBoundary fallback={<></>}>
            <Suspense fallback={null}>
                <entry.Suffix nav={nav} />
            </Suspense>
        </PostHogErrorBoundary>
    ) : null
}
