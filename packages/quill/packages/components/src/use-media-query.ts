import * as React from 'react'

/** The first client render already has the answer, so a layout chosen from it does not flash the other one. */
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
