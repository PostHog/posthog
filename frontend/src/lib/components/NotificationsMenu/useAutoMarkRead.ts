import { useEffect, useLayoutEffect, useRef } from 'react'
import { useInView } from 'react-intersection-observer'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'

export const AUTO_MARK_READ_DWELL_MS = 3000

// The row must be at least half on-screen before the dwell timer starts, so items
// barely peeking past the scroll edges don't get marked read.
const VISIBILITY_THRESHOLD = 0.5

/**
 * Marks a notification (or collapsed group) read once it has stayed continuously
 * visible in the viewport for `dwellMs`. Scrolling it out of view — or the browser
 * tab becoming hidden — resets the timer, so the dwell must be uninterrupted.
 * `onDwell` fires at most once per mounted item.
 *
 * `active` gates the whole thing: pass the item's unread state so an already-read
 * item is never observed, and pass false to disarm (e.g. an expanded group whose
 * children mark themselves read individually).
 *
 * Returns the ref callback to attach to the element whose visibility should count.
 */
export function useAutoMarkRead(
    active: boolean,
    onDwell: () => void,
    dwellMs: number = AUTO_MARK_READ_DWELL_MS
): (node?: Element | null) => void {
    const { ref, inView } = useInView({ threshold: VISIBILITY_THRESHOLD, skip: !active })
    const { isVisible: pageVisible } = usePageVisibility()

    // Hold onDwell behind a ref so a non-memoized inline callback doesn't reset the
    // dwell timer on every parent re-render.
    const onDwellRef = useRef(onDwell)
    useLayoutEffect(() => {
        onDwellRef.current = onDwell
    })

    const firedRef = useRef(false)

    useEffect(() => {
        if (!active || firedRef.current || !inView || !pageVisible) {
            return
        }
        const timer = setTimeout(() => {
            firedRef.current = true
            onDwellRef.current()
        }, dwellMs)
        return () => clearTimeout(timer)
    }, [active, inView, pageVisible, dwellMs])

    return ref
}
