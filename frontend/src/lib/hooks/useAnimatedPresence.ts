import { RefObject, useEffect, useLayoutEffect, useRef, useState } from 'react'

export interface AnimatedPresenceState {
    rendered: boolean
    shown: boolean
}

/**
 * Mount/unmount transition primitive — the project's standard way to drive an
 * enter/exit CSS animation around a component that should fully unmount when
 * hidden. Prefer this over adding new transition libraries (we removed
 * react-transition-group in favour of it).
 *
 * Returns `{ rendered, shown }`:
 * - gate rendering on `rendered`
 * - apply your "shown" CSS class / inline style based on `shown`
 *
 * `rendered !== shown` while a transition is mid-flight, so call sites that
 * need an `aria-busy`-style signal can derive it from those two booleans.
 *
 * Pass `ref` (pointing at the transitioning element) when the enter animation
 * must be reliable. Without it the flip to `shown` is deferred with rAF, which
 * only *usually* lets the pre-transition styles paint first — under load the
 * mount and the flip can coalesce into one paint and the enter transition is
 * skipped. With a ref, the flip forces a synchronous reflow instead, which
 * deterministically records the hidden state as the transition's start value.
 */
export function useAnimatedPresence(
    isIn: boolean,
    durationMs: number,
    ref?: RefObject<HTMLElement | null>
): AnimatedPresenceState {
    const [rendered, setRendered] = useState(isIn)
    const [shown, setShown] = useState(isIn)
    const renderedRef = useRef(rendered)
    renderedRef.current = rendered

    useEffect(() => {
        if (isIn) {
            setRendered(true)
            return
        }
        if (!renderedRef.current) {
            return
        }
        setShown(false)
        const timer = window.setTimeout(() => setRendered(false), durationMs)
        return () => window.clearTimeout(timer)
    }, [isIn, durationMs])

    // Flip `shown` on only once the hidden element is mounted, and make the
    // browser commit that hidden state as the transition's start value first —
    // otherwise the mount and the flip land in one paint and the enter
    // transition never runs.
    useLayoutEffect(() => {
        if (!isIn || !rendered || shown) {
            return
        }
        const node = ref?.current
        if (node) {
            // Force a synchronous layout so the hidden styles are the recorded
            // start value; the flip below then animates from them. Deterministic,
            // unlike frame-counting.
            void node.offsetHeight
            setShown(true)
            return
        }
        // Headless fallback (no node to reflow): defer two frames so the hidden
        // state has a chance to paint before the flip. Best-effort — pass a ref
        // when the transition must be reliable.
        let innerRaf = 0
        const outerRaf = window.requestAnimationFrame(() => {
            innerRaf = window.requestAnimationFrame(() => setShown(true))
        })
        return () => {
            window.cancelAnimationFrame(outerRaf)
            window.cancelAnimationFrame(innerRaf)
        }
    }, [isIn, rendered, shown, ref])

    return { rendered, shown }
}
