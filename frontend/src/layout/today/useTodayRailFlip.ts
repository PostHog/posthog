import { RefObject, useLayoutEffect, useRef } from 'react'

// Tiles already on the rail move to their new place, so they ease in and out. A tile that joins the rail enters.
const EASE_IN_OUT_CUBIC = 'cubic-bezier(0.645, 0.045, 0.355, 1)'
const EASE_OUT_QUINT = 'cubic-bezier(0.23, 1, 0.32, 1)'
const MOVE_MS = 250
const ENTER_MS = 200

/**
 * Animates the rail's tiles into place when the list of panes changes, so a pane shown, hidden or moved slides
 * rather than jumps. Each direct child of the container is keyed by its `data-flip-key`. Only transform and opacity
 * animate, so nothing reflows.
 */
export function useTodayRailFlip(container: RefObject<HTMLElement>, keys: string[], enabled: boolean): void {
    const lastRects = useRef<Map<string, DOMRect>>(new Map())
    const signature = keys.join(',')

    useLayoutEffect(() => {
        const element = container.current
        if (!element) {
            return
        }
        const children = Array.from(element.children) as HTMLElement[]
        const rects = new Map<string, DOMRect>()
        for (const child of children) {
            const key = child.dataset.flipKey
            if (key) {
                rects.set(key, child.getBoundingClientRect())
            }
        }
        const previous = lastRects.current
        lastRects.current = rects

        const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
        if (!enabled || reducedMotion || previous.size === 0) {
            return
        }
        for (const child of children) {
            const key = child.dataset.flipKey
            const now = key ? rects.get(key) : undefined
            if (!key || !now) {
                continue
            }
            const before = previous.get(key)
            if (!before) {
                child.animate(
                    [
                        { opacity: 0, transform: 'scale(0.95)' },
                        { opacity: 1, transform: 'none' },
                    ],
                    { duration: ENTER_MS, easing: EASE_OUT_QUINT }
                )
                continue
            }
            const dy = before.top - now.top
            if (Math.abs(dy) > 0.5) {
                child.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], {
                    duration: MOVE_MS,
                    easing: EASE_IN_OUT_CUBIC,
                })
            }
        }
        // `signature` stands in for `keys`, which is a new array on every render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [signature, enabled, container])
}
