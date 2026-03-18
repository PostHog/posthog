/**
 * Registry for custom nav icons that need dynamic behavior (e.g., badges, counters).
 *
 * Products can register custom icon components here to override the default static icons.
 * The registry maps item `type` values to React components.
 */
import { SupportNavBadge } from 'products/conversations/frontend/components/SupportNavBadge'

/**
 * Map of item types to custom icon components.
 * When an item's `type` matches a key here, the custom component is used instead of iconForType.
 */
export const customIconRegistry: Record<string, React.ComponentType<{ className?: string }>> = {
    conversations: SupportNavBadge,
}

/**
 * Get a custom icon component for the given type, or undefined if none registered.
 */
export function getCustomIcon(type: string | undefined): React.ComponentType<{ className?: string }> | undefined {
    if (!type) {
        return undefined
    }
    return customIconRegistry[type]
}
