const RECENT_MOVE_MS = 1000

let tracking = false
let lastMoveAt = Number.NEGATIVE_INFINITY

/** Starts the listener. Call it before the first card can open, so the first card already knows the pointer. */
export function trackPointer(): void {
    if (tracking) {
        return
    }
    tracking = true
    window.addEventListener(
        'pointermove',
        () => {
            lastMoveAt = performance.now()
        },
        { passive: true }
    )
}

/** Whether a hover comes from the pointer moving, not from the page scrolling under a resting pointer. */
export function pointerMovedRecently(): boolean {
    return performance.now() - lastMoveAt < RECENT_MOVE_MS
}
