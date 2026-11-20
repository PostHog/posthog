import * as React from 'react'

/**
 * Whether the viewport matches `query`. The value updates when the viewport changes.
 *
 * The first client render already has the answer, so a layout chosen from it does not flash the other layout first.
 */
function useMediaQuery(query: string): boolean {
    const subscribe = React.useCallback(
        (onChange: () => void) => {
            const list = window.matchMedia(query)
            list.addEventListener('change', onChange)
            return () => list.removeEventListener('change', onChange)
        },
        [query]
    )
    return React.useSyncExternalStore(
        subscribe,
        () => window.matchMedia(query).matches,
        // A server render cannot know the viewport. It assumes no match, and the client corrects it on hydration.
        () => false
    )
}

export { useMediaQuery }
