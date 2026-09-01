import { useEffect, useLayoutEffect, useRef } from 'react'
import { useInView } from 'react-intersection-observer'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'

export interface ContinuousDwellOptions {
    /** While false the element is not observed and `onDwell` can never fire. */
    active: boolean
    onDwell: () => void
    /** Uninterrupted milliseconds the element must stay visible before `onDwell` fires. */
    dwellMs: number
    /** Fraction of the element that must be inside the viewport to count as visible. */
    threshold: number
}

/**
 * Calls `onDwell` once the element has stayed continuously visible for `dwellMs`.
 *
 * Visible means both inside the viewport and in a foregrounded tab. Scrolling the element away or
 * backgrounding the tab restarts the timer from zero, so the caller measures attention rather than
 * elapsed wall-clock time. `onDwell` fires at most once per mounted element.
 *
 * Returns the ref callback to attach to the element whose visibility should count.
 */
export function useContinuousDwell({
    active,
    onDwell,
    dwellMs,
    threshold,
}: ContinuousDwellOptions): (node?: Element | null) => void {
    const { ref, inView } = useInView({ threshold, skip: !active })
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
