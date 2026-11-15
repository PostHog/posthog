/** Snapshot runners wait for no `pending` canvas: a screenshot between a wipe and its repaint shows a stale plot. */
const PAINT_STATE_ATTRIBUTE = 'data-hog-charts-paint'

export function markPaintPending(canvas: HTMLCanvasElement): void {
    canvas.setAttribute(PAINT_STATE_ATTRIBUTE, 'pending')
}

export function markPaintDone(canvas: HTMLCanvasElement): void {
    canvas.setAttribute(PAINT_STATE_ATTRIBUTE, 'done')
}
