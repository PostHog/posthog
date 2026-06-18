import { useEffect, useLayoutEffect, useRef, useSyncExternalStore } from 'react'

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
 * The callback is invoked exactly once on mount with the current visibility, then on every
 * subsequent visibilitychange. The hook stores the callback behind a ref so consumers passing a
 * non-memoized inline function do not re-invoke the effect (and therefore do not re-fire the
 * callback) on every parent render — that would dispatch side effects like pause/resume on
 * unrelated state churn.
 *
 * Without the mount-time invocation, tabs loaded while hidden (e.g. via "Open in background tab"
 * or after a multi-tab refresh while focus stays on one tab) never receive a "hidden" signal —
 * consumers like the experiment / dashboard auto-refresh intervals would then run on a tab the
 * user can't see.
 *
 * @param callback called with true if the page is visible, false if hidden
 */
export function usePageVisibilityCb(callback: (pageIsVisible: boolean) => void): void {
    const callbackRef = useRef(callback)
    // Update the ref in a commit-phase effect rather than during render so an
    // aborted concurrent render cannot expose an uncommitted callback to the
    // already-registered visibilitychange listener.
    useLayoutEffect(() => {
        callbackRef.current = callback
    })

    useEffect(() => {
        const onVisibilityChange = (): void => {
            callbackRef.current(isPageVisible())
        }

        callbackRef.current(isPageVisible())
        document.addEventListener(VISIBILITY_CHANGE_EVENT, onVisibilityChange)

        return function cleanUp() {
            document.removeEventListener(VISIBILITY_CHANGE_EVENT, onVisibilityChange)
        }
    }, [])
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
