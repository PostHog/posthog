import { useEffect, useState } from 'react'

/**
 * Gates a raw hover index behind a short dwell so a cursor merely passing over the
 * sparkline on its way elsewhere doesn't engage the headline. While disengaged, every
 * change to the raw index re-arms the timer, so only a pointer that settles on a point
 * past `delayMs` crosses the threshold. Once engaged the index tracks live; returning
 * to the resting index (a negative value) disengages immediately.
 *
 * `delayMs <= 0` opts out entirely — the raw index passes through unchanged.
 */
export function useHoverIntent(rawIndex: number, delayMs: number): number {
    const [engaged, setEngaged] = useState(false)

    useEffect(() => {
        if (delayMs <= 0) {
            return
        }
        if (rawIndex < 0) {
            // Pointer left the sparkline — disengage right away so the headline settles back.
            setEngaged(false)
            return
        }
        if (engaged) {
            return
        }
        // Re-armed on each move while disengaged; only a settled pointer reaches this timeout.
        const timer = setTimeout(() => setEngaged(true), delayMs)
        return () => clearTimeout(timer)
    }, [rawIndex, engaged, delayMs])

    if (delayMs <= 0) {
        return rawIndex
    }
    return engaged ? rawIndex : -1
}
