import type { MouseEvent as ReactMouseEvent } from 'react'

import { EditModeEdge } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'

/** Matches the 2rem corner handle hit areas in DashboardItems.scss, so the replayed press lands on the handle that would be under the cursor. */
const CORNER_THRESHOLD_PX = 32
/** How many animation frames to wait for edit mode to render before giving up on continuing the gesture. */
const MAX_FRAMES_TO_WAIT = 10
/** Above react-grid-layout's own 3px drag threshold, because entering edit mode costs more to undo than a stray drag. */
export const EDIT_MODE_GESTURE_THRESHOLD_PX = 8

/** `onDragStarted` receives the move that crossed the threshold, which react-grid-layout needs to resume the gesture. */
export function whenPressBecomesDrag(event: ReactMouseEvent, onDragStarted: (moveEvent: MouseEvent) => void): void {
    const { clientX, clientY } = event

    function stopWatching(): void {
        window.removeEventListener('mousemove', handleMove, { capture: true })
        window.removeEventListener('mouseup', stopWatching, { capture: true })
    }

    function handleMove(moveEvent: MouseEvent): void {
        // A release outside the browser window never delivers mouseup here, so trust what the move
        // reports is still held rather than the release we may never see.
        if (!(moveEvent.buttons & 1)) {
            stopWatching()
            return
        }
        const travelled = Math.hypot(moveEvent.clientX - clientX, moveEvent.clientY - clientY)
        if (travelled < EDIT_MODE_GESTURE_THRESHOLD_PX) {
            return
        }
        stopWatching()
        onDragStarted(moveEvent)
    }

    window.addEventListener('mousemove', handleMove, { capture: true })
    window.addEventListener('mouseup', stopWatching, { capture: true })
}

/** Pick the resize handle direction for a press on a tile edge, upgrading presses near a corner to the corner handle. */
export function resolveResizeHandleDirection(
    edge: EditModeEdge,
    rect: { left: number; right: number; top: number; bottom: number },
    clientX: number,
    clientY: number
): string {
    // Corner presses already name the diagonal handle directly.
    if (['nw', 'ne', 'sw', 'se'].includes(edge)) {
        return edge
    }
    if (edge === 'n' || edge === 's') {
        if (clientX - rect.left <= CORNER_THRESHOLD_PX) {
            return `${edge}w`
        }
        if (rect.right - clientX <= CORNER_THRESHOLD_PX) {
            return `${edge}e`
        }
        return edge
    }
    if (clientY - rect.top <= CORNER_THRESHOLD_PX) {
        return `n${edge}`
    }
    if (rect.bottom - clientY <= CORNER_THRESHOLD_PX) {
        return `s${edge}`
    }
    return edge
}

/**
 * Re-dispatch the pressed-down mouse event on `findTarget()` once it becomes available, so a gesture started
 * before edit mode rendered continues without the user having to release and press again. react-grid-layout
 * only listens for mousedown while drag/resize is enabled, so the original press never reaches it.
 */
function replayMouseDown(event: ReactMouseEvent, findTarget: () => Element | null, pointerNow: MouseEvent): void {
    const { clientX, clientY, button } = event
    let cancelled = false
    const cancel = (): void => {
        cancelled = true
    }
    // If the button is released before edit mode renders, replaying would leave a drag/resize stuck "in progress"
    window.addEventListener('mouseup', cancel, { capture: true, once: true })

    let framesLeft = MAX_FRAMES_TO_WAIT
    const tryReplay = (): void => {
        if (cancelled) {
            return
        }
        const target = findTarget()
        if (!target) {
            framesLeft -= 1
            if (framesLeft > 0) {
                requestAnimationFrame(tryReplay)
            } else {
                window.removeEventListener('mouseup', cancel, { capture: true })
            }
            return
        }
        window.removeEventListener('mouseup', cancel, { capture: true })
        target.dispatchEvent(
            new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window, clientX, clientY, button })
        )
        // Replaying the press at its origin keeps the tile from jumping, but leaves react-grid-layout
        // believing the pointer never moved. This hands it the travel it missed.
        target.ownerDocument.dispatchEvent(
            new MouseEvent('mousemove', {
                bubbles: true,
                cancelable: true,
                view: window,
                clientX: pointerNow.clientX,
                clientY: pointerNow.clientY,
                button,
            })
        )
    }
    requestAnimationFrame(tryReplay)
}

/** Continue a press on a tile edge into a live resize once edit mode's resize handles have rendered. */
export function continueResizeGestureInEditMode(
    event: ReactMouseEvent,
    edge: EditModeEdge,
    pointerNow: MouseEvent
): void {
    const gridItem = (event.target as Element | null)?.closest('.react-grid-item')
    if (!gridItem) {
        return
    }
    const rect = gridItem.getBoundingClientRect()
    const direction = resolveResizeHandleDirection(edge, rect, event.clientX, event.clientY)
    replayMouseDown(event, () => gridItem.querySelector(`.react-resizable-handle-${direction}`), pointerNow)
}

/** Continue a press on a tile's drag handle into a live drag once edit mode has enabled dragging. */
export function continueDragGestureInEditMode(event: ReactMouseEvent, pointerNow: MouseEvent): void {
    const target = event.target as Element | null
    const gridItem = target?.closest('.react-grid-item')
    if (!target || !gridItem) {
        return
    }
    replayMouseDown(
        event,
        () =>
            // the grid signals that dragging is live by swapping to the edit-mode class
            target.isConnected && gridItem.closest('.react-grid-layout.dashboard-edit-mode') ? target : null,
        pointerNow
    )
}
