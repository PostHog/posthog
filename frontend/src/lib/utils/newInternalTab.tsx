import { router } from 'kea-router'

// Retained as a no-op dispatch type for any legacy listeners.
export const NEW_INTERNAL_TAB = 'NEW_INTERNAL_TAB'

/**
 * PostHog tabs were removed — this helper used to open a new internal tab,
 * but now simply navigates the current page to the given path.
 */
export function newInternalTab(path?: string, _source: 'internal_link' | 'unknown' = 'internal_link'): void {
    if (path) {
        router.actions.push(path)
    }
}
