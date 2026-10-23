import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

/**
 * Registry for custom nav icons that need dynamic behavior (e.g., badges, counters).
 *
 * Products can register custom icon components here to override the default static icons.
 * The registry maps item `type` values to React components.
 */
import { SupportNavBadge } from 'products/conversations/frontend/components/SupportNavBadge'
import { SupportNavCount } from 'products/conversations/frontend/components/SupportNavCount/SupportNavCount'

/**
 * Map of item types to custom icon components.
 * When an item's `type` matches a key here, the custom component is used instead of iconForType.
 */
export const customIconRegistry: Record<string, React.ComponentType<{ className?: string }>> = {
    conversations: SupportNavBadge,
}

/**
 * Map of item types to count components, for navigation that shows a count at the end of the row
 * instead of on the icon. A count component renders nothing when there is nothing to count.
 */
export const customCountRegistry: Record<string, React.ComponentType> = {
    conversations: SupportNavCount,
}

function registryType(type: string | undefined, href: string | undefined): string | undefined {
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
    return type
}

/**
 * Get a custom icon component for the given type, or undefined if none registered.
 */
export function getCustomIcon(
    type: string | undefined,
    href: string | undefined
): React.ComponentType<{ className?: string }> | undefined {
    const key = registryType(type, href)
    return key ? customIconRegistry[key] : undefined
}

/**
 * Get a count component for the given type, or undefined if none registered.
 */
export function getCustomCount(type: string | undefined, href: string | undefined): React.ComponentType | undefined {
    const key = registryType(type, href)
    return key ? customCountRegistry[key] : undefined
}
