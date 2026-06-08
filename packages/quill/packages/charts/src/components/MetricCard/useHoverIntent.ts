import { useEffect, useState } from 'react'

/**
 * Debounces a sparkline hover index so a cursor merely passing over the card on its way
 * elsewhere doesn't swap the headline — the pointer has to settle on a point for `delayMs`
 * before it takes effect. Leaving the sparkline (a negative index) applies immediately, so
 * the headline drops straight back to rest. `delayMs <= 0` opts out.
 *
 * Mirrors the app's `useDebouncedValue`, which this standalone package can't import.
 */
export function useHoverIntent(rawIndex: number, delayMs: number): number {
    const [settledIndex, setSettledIndex] = useState(rawIndex)

    useEffect(() => {
        if (delayMs <= 0 || rawIndex < 0) {
            setSettledIndex(rawIndex)
            return
        }
        const timer = setTimeout(() => setSettledIndex(rawIndex), delayMs)
        return () => clearTimeout(timer)
    }, [rawIndex, delayMs])

    return delayMs <= 0 || rawIndex < 0 ? rawIndex : settledIndex
}
