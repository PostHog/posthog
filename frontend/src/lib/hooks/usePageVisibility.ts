import { useCallback, useEffect, useState } from 'react'

// Determine the correct hidden property name for browser compatibility
// adapted from https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API#example
// Opera 12.10 and Firefox 18 and later support
function getHiddenProperty(): string {
    // @ts-expect-error - to avoid complaint that msHidden isn't on document
    if (typeof document.msHidden !== 'undefined') {
        return 'msHidden'
    }
    // @ts-expect-error - to avoid complaint that webkitHidden isn't on document
    if (typeof document.webkitHidden !== 'undefined') {
        return 'webkitHidden'
    }
    return 'hidden'
}

function getVisibilityChangeEvent(): string {
    // @ts-expect-error - to avoid complaint that msHidden isn't on document
    if (typeof document.msHidden !== 'undefined') {
        return 'msvisibilitychange'
    }
    // @ts-expect-error - to avoid complaint that webkitHidden isn't on document
    if (typeof document.webkitHidden !== 'undefined') {
        return 'webkitvisibilitychange'
    }
    return 'visibilitychange'
}

function isPageVisible(): boolean {
    const hidden = getHiddenProperty()
    return !document[hidden as keyof Document]
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
        const visibilityChange = getVisibilityChangeEvent()

        const onVisibilityChange = (): void => {
            callback(isPageVisible())
        }

        document.addEventListener(visibilityChange, onVisibilityChange)

        return function cleanUp() {
            document.removeEventListener(visibilityChange, onVisibilityChange)
        }
    }, [callback])
}

/**
 * Hook that returns the current page visibility state and triggers re-renders when it changes.
 */
export function usePageVisibility(): { isVisible: boolean } {
    const [, forceUpdate] = useState({})

    const handleVisibilityChange = useCallback(() => {
        forceUpdate({}) // Force trigger re-render
    }, [])

    usePageVisibilityCb(handleVisibilityChange)

    // Always get browser's state directly in case render is needed
    // before this hook's forceUpdate has run (avoids flashing stale state)
    return { isVisible: isPageVisible() }
}
