import { useEffect } from 'react'
// @ts-expect-error - useSyncExternalStore is available in React 18 but types are v17
import { useSyncExternalStore } from 'react'

// Determine the correct hidden property name and change event for browser compatibility
// adapted from https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API#example
// Opera 12.10 and Firefox 18 and later support
const { HIDDEN_PROPERTY, VISIBILITY_CHANGE_EVENT } = (() => {
    if (typeof document !== 'undefined') {
        if ('msHidden' in document) {
            return { HIDDEN_PROPERTY: 'msHidden', VISIBILITY_CHANGE_EVENT: 'msvisibilitychange' }
        }
        if ('webkitHidden' in document) {
            return { HIDDEN_PROPERTY: 'webkitHidden', VISIBILITY_CHANGE_EVENT: 'webkitvisibilitychange' }
        }
    }
    return { HIDDEN_PROPERTY: 'hidden', VISIBILITY_CHANGE_EVENT: 'visibilitychange' }
})()

function isPageVisible(): boolean {
    return !document[HIDDEN_PROPERTY as keyof Document]
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
 * @param callback when page visibility changes this is called with true if the page is visible and false otherwise
 */
export function usePageVisibilityCb(callback: (pageIsVisible: boolean) => void): void {
    useEffect(() => {
        const onVisibilityChange = (): void => {
            callback(isPageVisible())
        }

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
