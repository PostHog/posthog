import type { MouseEvent } from 'react'

// A right click on these keeps the browser menu, because it has actions such as "Open link in new tab".
const NATIVE_CONTEXT_MENU_SELECTOR = 'a[href], input, select, textarea'

export interface ResultMenuPoint {
    x: number
    y: number
    timestamp: number
}

export function isResultMenuContextMenu(event: MouseEvent<HTMLElement>): boolean {
    const target = event.target as Element
    return event.currentTarget.contains(target) && !target.closest(NATIVE_CONTEXT_MENU_SELECTOR)
}

export function getResultMenuPoint(event: MouseEvent): ResultMenuPoint {
    // A menu opened from the keyboard has no pointer position, so anchor it to the focused element.
    if (!event.clientX && !event.clientY) {
        const rect = (event.target as Element).getBoundingClientRect()
        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, timestamp: event.timeStamp }
    }
    return { x: event.clientX, y: event.clientY, timestamp: event.timeStamp }
}

// Most visualizations select a result only in a click handler. Replaying the right click as a click runs
// that handler, so the menu can capture the result that a left click acts on.
export function replayAsClick(event: MouseEvent): void {
    event.target.dispatchEvent(
        new window.MouseEvent('click', {
            bubbles: true,
            cancelable: true,
            view: window,
            detail: 1,
            clientX: event.clientX,
            clientY: event.clientY,
            screenX: event.screenX,
            screenY: event.screenY,
        })
    )
}
