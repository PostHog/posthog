/**
 * The "use this name anyway" option, offered when a caller sets
 * `allowNonCapturedEvents` and the search matches no captured event.
 *
 * Both pickers commit this same shape, so a caller reads one item on either
 * surface. `useGroupList` and `infiniteListLogic` hold the matching
 * `showNonCapturedEventOption` guards.
 */

/** Synthetic item committed for an event PostHog has not captured yet. */
export interface NonCapturedEventItem {
    name: string
    isNonCaptured: true
}

export function buildNonCapturedEventItem(name: string): NonCapturedEventItem {
    return { name, isNonCaptured: true }
}

export function isNonCapturedEventItem(item: unknown): boolean {
    return !!item && typeof item === 'object' && (item as { isNonCaptured?: boolean }).isNonCaptured === true
}
