import { useSyncExternalStore } from 'react'

const SETTLE_MS = 150

// One `visualViewport` listener serves every chart on the page, so a page of charts does not
// register one listener and one settle timer per chart.
const listeners = new Set<() => void>()
let settleTimer: ReturnType<typeof setTimeout> | undefined

// The package must import without a DOM (server rendering, the build's `check:node-import` step),
// so the module-level read below cannot assume `window`.
const read = (): number =>
    typeof window === 'undefined' ? 1 : (window.devicePixelRatio || 1) * Math.max(1, window.visualViewport?.scale ?? 1)
let settled = read()

// Chrome fires `visualViewport` resize for a pinch-zoom and for a move to a screen with another
// pixel ratio. Wait for it to settle, because a new ratio per gesture frame redraws every chart in
// view at a growing size.
function onViewportResize(): void {
    clearTimeout(settleTimer)
    settleTimer = setTimeout(() => {
        const next = read()
        if (next !== settled) {
            settled = next
            listeners.forEach((listener) => listener())
        }
    }, SETTLE_MS)
}

function subscribe(listener: () => void): () => void {
    if (listeners.size === 0) {
        settled = read()
        window.visualViewport?.addEventListener('resize', onViewportResize)
    }
    listeners.add(listener)
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
            window.visualViewport?.removeEventListener('resize', onViewportResize)
            clearTimeout(settleTimer)
        }
    }
}

/** Device pixels per CSS pixel on screen: `devicePixelRatio` times the pinch-zoom scale. */
export function useViewportPixelRatio(): number {
    return useSyncExternalStore(
        subscribe,
        () => settled,
        () => 1
    )
}
