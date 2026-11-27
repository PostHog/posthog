import { useValues } from 'kea'
import { lazy, Suspense } from 'react'

import { IconTableOfContents } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { lazyWithRetry, retryImport } from 'lib/utils/retryImport'

/**
 * Registry for custom nav icons that need dynamic behavior (e.g., badges, counters).
 *
 * Products can register custom icon components here to override the default static icons.
 * The registry maps item `type` values to React components.
 */
import { SupportNavBadge, useSupportUnreadCount } from 'products/conversations/frontend/components/SupportNavBadge'

const LazyDataCatalogNavBadge = lazyWithRetry(() =>
    import('products/data_catalog/frontend/components/DataCatalogNavBadge').then((module) => ({
        default: module.DataCatalogNavBadge,
    }))
)

function DataCatalogNavBadge({ className }: { className?: string }): JSX.Element {
    return (
        <Suspense fallback={<IconTableOfContents className={className} />}>
            <LazyDataCatalogNavBadge className={className} />
        </Suspense>
    )
}

function NoNavSuffix(): null {
    return null
}

const LazyAdventNavTree = lazy<() => JSX.Element | null>(() =>
    retryImport(() => import('products/workflows/frontend/AdventCalendar/AdventNavTree')).then(
        (module) => ({ default: module.AdventNavTree }),
        () => ({ default: NoNavSuffix })
    )
)

function WorkflowsNavSuffix(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]) {
        return null
    }
    return (
        <Suspense fallback={null}>
            <LazyAdventNavTree />
        </Suspense>
    )
}

/**
 * Map of item types to custom icon components.
 * When an item's `type` matches a key here, the custom component is used instead of iconForType.
 */
export const customIconRegistry: Record<string, React.ComponentType<{ className?: string }>> = {
    conversations: SupportNavBadge,
    data_catalog: DataCatalogNavBadge,
}

/**
 * Hooks that give a nav item's count, for navs that show the count as text instead of on the icon. They use the same
 * logic as the icons above, so a count is never fetched twice.
 */
export const customNavCountRegistry = {
    conversations: useSupportUnreadCount,
} satisfies Record<string, () => number>

const customNavSuffixRegistry: Record<string, React.ComponentType> = {
    workflows: WorkflowsNavSuffix,
}

export function CustomNavSuffix({ type }: { type?: string }): JSX.Element | null {
    const Suffix = type ? customNavSuffixRegistry[type] : undefined
    return Suffix ? <Suffix /> : null
}

/**
 * Get a custom icon component for the given type, or undefined if none registered.
 */
export function getCustomIcon(
    type: string | undefined,
    href: string | undefined
): React.ComponentType<{ className?: string }> | undefined {
    if (!type) {
        return undefined
    }
    // Starred links store the icon type, which other apps can share with Support.
    if (type === 'conversations') {
        const pathname = removeProjectIdIfPresent(href ?? '').split(/[?#]/)[0]
        if (pathname !== '/support' && !pathname.startsWith('/support/')) {
            return undefined
        }
    }
    return customIconRegistry[type]
}
