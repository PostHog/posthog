import { useEffect, useRef, useState } from 'react'

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
 */
export function useAnimatedPresence(isIn: boolean, durationMs: number): AnimatedPresenceState {
    const [rendered, setRendered] = useState(isIn)
    const [shown, setShown] = useState(isIn)
    const renderedRef = useRef(rendered)
    renderedRef.current = rendered

    useEffect(() => {
        if (isIn) {
            setRendered(true)
            // Defer the visibility flip a frame so the browser paints the
            // pre-transition (hidden) styles first; without this RAF the
            // browser coalesces both states into one paint and the CSS
            // transition never runs.
            const raf = window.requestAnimationFrame(() => setShown(true))
            return () => window.cancelAnimationFrame(raf)
        }
        if (!renderedRef.current) {
            return
        }
        setShown(false)
        const timer = window.setTimeout(() => setRendered(false), durationMs)
        return () => window.clearTimeout(timer)
    }, [isIn, durationMs])

    return { rendered, shown }
}
