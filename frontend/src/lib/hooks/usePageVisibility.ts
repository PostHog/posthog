import { useEffect, useSyncExternalStore } from 'react'

// See https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API
const VISIBILITY_CHANGE_EVENT = 'visibilitychange'

function isPageVisible(): boolean {
    return !document.hidden
}

/**
 *
 * The Page Visibility API provides events you can watch for to know when a document becomes visible or hidden,
 * as well as features to look at the current visibility state of the page.
 *
 * When the user minimizes the window or switches to another tab, the API sends a visibilitychange event
 * to let listeners know the state of the page has changed.
 *
 * see https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API
 *
 * The callback is invoked once on mount with the current visibility, and again on every
 * visibilitychange. Without the mount-time invocation, tabs loaded while hidden (e.g. via
 * "Open in background tab" or after a multi-tab refresh while focus stays on one tab) never
 * receive a "hidden" signal — consumers like the experiment / dashboard auto-refresh
 * intervals would then run on a tab the user can't see.
 *
 * @param callback called with true if the page is visible, false if hidden
 */
export function usePageVisibilityCb(callback: (pageIsVisible: boolean) => void): void {
    useEffect(() => {
        const onVisibilityChange = (): void => {
            callback(isPageVisible())
        }

        callback(isPageVisible())
        document.addEventListener(VISIBILITY_CHANGE_EVENT, onVisibilityChange)

        return function cleanUp() {
            document.removeEventListener(VISIBILITY_CHANGE_EVENT, onVisibilityChange)
        }
    }, [callback])
}

/**
 * Hook that returns the current page visibility state and triggers re-renders when it changes.
 */
export function usePageVisibility(): { isVisible: boolean } {
    const isVisible = useSyncExternalStore(
        (callback: () => void) => {
            document.addEventListener(VISIBILITY_CHANGE_EVENT, callback)
            return () => document.removeEventListener(VISIBILITY_CHANGE_EVENT, callback)
        },
        () => isPageVisible()
    )

    return { isVisible }
}
