const RECENT_MOVE_MS = 1000
// Small jitters while the pointer rests on a link must not flip the direction.
const DIRECTION_THRESHOLD_PX = 6

let tracking = false
let lastMoveAt = Number.NEGATIVE_INFINITY
let anchorY: number | null = null
let movingUp = false

/** Starts the listener. Call it before the first card can open, so the first card already knows the pointer. */
export function trackPointer(): void {
    if (tracking) {
        return
    }
    tracking = true
    window.addEventListener(
        'pointermove',
        (event) => {
            lastMoveAt = performance.now()
            const delta = event.clientY - (anchorY ?? event.clientY)
            if (anchorY === null || Math.abs(delta) >= DIRECTION_THRESHOLD_PX) {
                movingUp = delta < 0
                anchorY = event.clientY
            }
        },
        { passive: true }
    )
}

/** Whether a hover comes from the pointer moving, not from the page scrolling under a resting pointer. */
export function pointerMovedRecently(): boolean {
    return performance.now() - lastMoveAt < RECENT_MOVE_MS
}

/** Above a link when the pointer comes down the text, below when it goes up, so the card leaves the next link free. */
export function cardSideForPointer(): 'top' | 'bottom' {
    return movingUp ? 'bottom' : 'top'
}
