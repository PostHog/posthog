import { addProjectIdIfMissing } from 'lib/utils/router-utils'

export const NEW_INTERNAL_TAB = 'NEW_INTERNAL_TAB'

/**
 * Open a path in a new browser tab. Preserves project scoping for relative URLs.
 * `window.open(url, '_blank')` with no features string is routed to a tab by all
 * modern browsers when called from a user gesture; passing a features string flips
 * it to popup-window mode.
 */
export function newInternalTab(path?: string, _source: 'internal_link' | 'unknown' = 'internal_link'): void {
    if (!path) {
        return
    }
    const isExternal = /^(https?:|mailto:)/.test(path)
    const href = isExternal ? path : addProjectIdIfMissing(path)
    const opened = window.open(href, '_blank')
    if (opened) {
        opened.opener = null
    }
}
