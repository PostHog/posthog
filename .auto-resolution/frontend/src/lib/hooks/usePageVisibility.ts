import { useEffect, useState } from 'react'

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
        // adapted from https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API#example
        // Opera 12.10 and Firefox 18 and later support
        let hidden = 'hidden'
        let visibilityChange = 'visibilitychange'
        // @ts-expect-error - to avoid complaint that msHidden isn't on document
        if (typeof document.msHidden !== 'undefined') {
            hidden = 'msHidden'
            visibilityChange = 'msvisibilitychange'
            // @ts-expect-error - to avoid complaint that webkitHidden isn't on document
        } else if (typeof document.webkitHidden !== 'undefined') {
            hidden = 'webkitHidden'
            visibilityChange = 'webkitvisibilitychange'
        }

        const onVisibilityChange = (): void => {
            callback(!document[hidden])
        }

        document.addEventListener(visibilityChange, onVisibilityChange)

        return function cleanUp() {
            document.removeEventListener(visibilityChange, onVisibilityChange)
        }
    }, [callback])
}

export function usePageVisibility(): { isVisible: boolean } {
    const [isVisible, setIsVisible] = useState<boolean>(!document.hidden)

    usePageVisibilityCb((pageIsVisible) => {
        setIsVisible(pageIsVisible)
    })

    return { isVisible }
}
