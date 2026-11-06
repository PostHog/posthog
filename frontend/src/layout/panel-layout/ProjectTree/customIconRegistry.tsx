import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

/**
 * Registry for custom nav icons that need dynamic behavior (e.g., badges, counters).
 *
 * Products can register custom icon components here to override the default static icons.
 * The registry maps item `type` values to React components.
 */
import { SupportNavBadge, useSupportUnreadCount } from 'products/conversations/frontend/components/SupportNavBadge'

/**
 * Map of item types to custom icon components.
 * When an item's `type` matches a key here, the custom component is used instead of iconForType.
 */
export const customIconRegistry: Record<string, React.ComponentType<{ className?: string }>> = {
    conversations: SupportNavBadge,
}

/**
 * Hooks that give a nav item's count, for navs that show the count as text instead of on the icon. They use the same
 * logic as the icons above, so a count is never fetched twice.
 */
export const customNavCountRegistry = {
    conversations: useSupportUnreadCount,
} satisfies Record<string, () => number>

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
