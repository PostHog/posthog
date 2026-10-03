export const HOVER_OPEN_DELAY_MS = 250
export const HOVER_CLOSE_DELAY_MS = 120
export const HOVER_CARD_GAP_PX = 10

// The browser reports a hover when the page lays out under a resting cursor. A hover opens a card only
// when the pointer moved just before, so a card never opens by itself when the page loads.
const RECENT_MOVE_MS = 1000
let lastPointerMove = Number.NEGATIVE_INFINITY

if (typeof window !== 'undefined') {
    window.addEventListener('pointermove', () => (lastPointerMove = performance.now()), { passive: true })
}

export function pointerMovedRecently(): boolean {
    return performance.now() - lastPointerMove < RECENT_MOVE_MS
}

/** The card opens under the whole block of figures: the paragraph with its age line, or a key number. */
export function cardAnchor(trigger: HTMLElement | null): Element | undefined {
    return trigger?.closest('[data-today-figures]') ?? trigger?.closest('li, p') ?? undefined
}
