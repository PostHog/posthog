import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { openInOsWindow } from 'scenes/os/bridge/osFrameConnection'

export const NEW_INTERNAL_TAB = 'NEW_INTERNAL_TAB'

/**
 * Open a path in a new browser tab. Preserves project scoping for relative URLs.
 *
 * Dispatches a synthetic cmd/ctrl-click on an anchor — browsers treat modifier-clicks
 * on `<a target="_blank">` as "open in new tab" regardless of the user's `window.open`
 * preference, while plain `window.open` and bare `.click()` can route to a new window.
 */
export function newInternalTab(path?: string, _source: 'internal_link' | 'unknown' = 'internal_link'): void {
    if (!path) {
        return
    }
    const isExternal = /^(https?:|mailto:)/.test(path)
    const href = isExternal ? path : addProjectIdIfMissing(path)
    // Inside an OS window, a new tab of the app is a new window.
    if (!isExternal && openInOsWindow(href)) {
        return
    }

    const anchor = document.createElement('a')
    anchor.href = href
    anchor.target = '_blank'
    anchor.rel = 'noopener noreferrer'

    const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
    anchor.dispatchEvent(
        new MouseEvent('click', {
            bubbles: true,
            cancelable: true,
            view: window,
            ctrlKey: !isMac,
            metaKey: isMac,
        })
    )
}
