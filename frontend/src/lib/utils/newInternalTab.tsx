import { addProjectIdIfMissing } from 'lib/utils/router-utils'

export const NEW_INTERNAL_TAB = 'NEW_INTERNAL_TAB'

/**
 * Open a path in a new browser tab. Preserves project scoping for relative URLs.
 * Uses a synthetic anchor click so browsers route through their native tab handling
 * — `window.open(url, '_blank', features)` is treated as a popup window by some browsers.
 */
export function newInternalTab(path?: string, _source: 'internal_link' | 'unknown' = 'internal_link'): void {
    if (!path) {
        return
    }
    const isExternal = /^(https?:|mailto:)/.test(path)
    const href = isExternal ? path : addProjectIdIfMissing(path)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.target = '_blank'
    anchor.rel = 'noopener noreferrer'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
}
