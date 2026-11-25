import { useEffect, useState } from 'react'

// The next turns start loading this far before the reader reaches the end, so scrolling rarely waits on them.
const LOAD_AHEAD = '0px 0px 600px 0px'

/**
 * Calls `onNearEnd` when the sentinel the returned ref marks comes near the visible end of `scroller`, while `enabled`
 * holds. Each time `enabled` turns on the sentinel is checked again, so a page too short to scroll keeps loading.
 */
export function useNearEnd(
    scroller: HTMLElement | null,
    onNearEnd: () => void,
    enabled: boolean
): (sentinel: HTMLElement | null) => void {
    const [sentinel, setSentinel] = useState<HTMLElement | null>(null)

    useEffect(() => {
        if (!enabled || !scroller || !sentinel) {
            return
        }
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    onNearEnd()
                }
            },
            { root: scroller, rootMargin: LOAD_AHEAD }
        )
        observer.observe(sentinel)
        return () => observer.disconnect()
    }, [enabled, scroller, sentinel, onNearEnd])

    return setSentinel
}
