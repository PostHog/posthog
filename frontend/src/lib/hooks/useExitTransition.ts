import { useEffect, useRef, useState } from 'react'

export interface ExitTransitionState {
    mounted: boolean
    visible: boolean
}

/**
 * Mount/unmount transition primitive — the project's standard way to drive an
 * enter/exit CSS animation around a component that should fully unmount when
 * hidden. Prefer this over adding new transition libraries (we removed
 * react-transition-group in favour of it).
 *
 * Returns `{ mounted, visible }`:
 * - gate rendering on `mounted`
 * - apply your "visible" CSS class / inline style based on `visible`
 *
 * `mounted !== visible` while a transition is mid-flight, so call sites that
 * need an `aria-busy`-style signal can derive it from those two booleans.
 */
export function useExitTransition(isIn: boolean, durationMs: number): ExitTransitionState {
    const [mounted, setMounted] = useState(isIn)
    const [visible, setVisible] = useState(isIn)
    const mountedRef = useRef(mounted)
    mountedRef.current = mounted

    useEffect(() => {
        if (isIn) {
            setMounted(true)
            // Defer the visibility flip a frame so the browser paints the
            // pre-transition (hidden) styles first; without this RAF the
            // browser coalesces both states into one paint and the CSS
            // transition never runs.
            const raf = window.requestAnimationFrame(() => setVisible(true))
            return () => window.cancelAnimationFrame(raf)
        }
        if (!mountedRef.current) {
            return
        }
        setVisible(false)
        const timer = window.setTimeout(() => setMounted(false), durationMs)
        return () => window.clearTimeout(timer)
    }, [isIn, durationMs])

    return { mounted, visible }
}
