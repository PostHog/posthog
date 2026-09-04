import { router } from 'kea-router'

import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { isExternalLink } from 'lib/utils/url'

/** Search items with no real destination carry this href, so it must never be navigated to. */
export const PLACEHOLDER_HREF = '#'

/**
 * Navigate to an href the way `Link` does, for call sites that have an href but no anchor to
 * click — a command palette item, a menu row, a keyboard selection.
 *
 * `router.actions.push` reaches `history.pushState`, which rejects a cross-origin URL and, in
 * Safari, rate-limits repeat calls. Both raise a `SecurityError` that escapes the click handler
 * as an uncaught exception, so a page load is the fallback: the person still gets where they
 * asked to go.
 */
export function navigateToHref(href?: string): void {
    if (!href || href === PLACEHOLDER_HREF) {
        return
    }
    if (isExternalLink(href)) {
        window.location.href = href
        return
    }
    try {
        router.actions.push(href)
    } catch (error) {
        // Any other error comes from a logic reacting to the navigation, which already happened.
        // Reloading the page over it would hide the real failure.
        if (!(error instanceof DOMException) || error.name !== 'SecurityError') {
            throw error
        }
        window.location.href = addProjectIdIfMissing(href)
    }
}
