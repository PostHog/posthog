import { useValues } from 'kea'
import { Suspense } from 'react'

import { PostHogErrorBoundary } from '@posthog/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { ProductItemCategory } from '~/queries/schema/schema-general'

export type CategorySuffixNav = 'classic' | 'today'

const AdventNavTreeButton = lazyWithRetry(() =>
    import('products/workflows/frontend/AdventCalendar/entry/AdventNavTreeButton').then((module) => ({
        default: module.AdventNavTreeButton,
    }))
)

export function CustomCategorySuffix({
    category,
    nav,
}: {
    category: string
    nav: CategorySuffixNav
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    return category === ProductItemCategory.MESSAGING && featureFlags[FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR] ? (
        <PostHogErrorBoundary fallback={<></>}>
            <Suspense fallback={null}>
                <AdventNavTreeButton nav={nav} />
            </Suspense>
        </PostHogErrorBoundary>
    ) : null
}
