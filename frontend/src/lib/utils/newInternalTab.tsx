import { addProjectIdIfMissing } from 'lib/utils/kea-router'

export const NEW_INTERNAL_TAB = 'NEW_INTERNAL_TAB'

/**
 * Open a path in a new browser tab. Preserves project scoping for relative URLs.
 *
 * Clicks a real `<a target="_blank">` anchor attached to the DOM — a plain programmatic
 * click on such an anchor opens a new tab reliably. An earlier version dispatched a
 * synthetic cmd/ctrl-click, but browsers ignore modifier keys on untrusted events
 * (`isTrusted === false`), so in some environments no tab opened at all.
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
    anchor.style.display = 'none'

    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
}
