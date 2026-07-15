import { getContext } from 'kea'

import { addProjectIdIfMissing } from 'lib/utils/kea-router'

import { isDesktopApp } from './isDesktopApp'

export const NEW_INTERNAL_TAB = 'NEW_INTERNAL_TAB'

export interface NewInternalTabOptions {
    source?: 'internal_link' | 'unknown'
    /** Desktop app only: focus the new tab immediately instead of opening it in the background */
    activate?: boolean
    /** Desktop app only: initial tab title (e.g. the link text) until the scene loads and reports its own */
    title?: string
}

/**
 * Open a path in a new browser tab. Preserves project scoping for relative URLs.
 *
 * Dispatches a synthetic cmd/ctrl-click on an anchor — browsers treat modifier-clicks
 * on `<a target="_blank">` as "open in new tab" regardless of the user's `window.open`
 * preference, while plain `window.open` and bare `.click()` can route to a new window.
 *
 * In the desktop app (products/desktop) internal paths open as scene tabs in the
 * desktop tab strip instead: the NEW_INTERNAL_TAB action is picked up by sceneTabsLogic.
 */
export function newInternalTab(path?: string, options: NewInternalTabOptions = {}): void {
    if (!path) {
        return
    }
    const isExternal = /^(https?:|mailto:)/.test(path)
    if (isDesktopApp() && !isExternal) {
        getContext().store.dispatch({
            type: NEW_INTERNAL_TAB,
            payload: {
                path,
                source: options.source ?? 'internal_link',
                activate: options.activate,
                title: options.title,
            },
        })
        return
    }
    const href = isExternal ? path : addProjectIdIfMissing(path)

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
