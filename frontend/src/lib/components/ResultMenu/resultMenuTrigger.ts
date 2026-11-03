import type { MouseEvent } from 'react'

// A right click on these keeps the browser menu. Links and inputs have their own browser actions, and
// legend rows are not results, so a replayed click on them hides or isolates a series.
const NATIVE_CONTEXT_MENU_SELECTOR =
    'a[href], input, select, textarea, label, [data-hog-charts-legend], .InsightLegendMenu'

// A replayed click must not reach these. A marked chart selects its result on right click already, and a click
// on that chart or its tooltip can pin the tooltip or open the insight instead.
const NO_REPLAY_SELECTOR = '[data-hog-charts-context-menu], [data-hog-charts-tooltip]'

export interface ResultMenuPoint {
    x: number
    y: number
    timestamp: number
}

// A context menu that a child already opened, such as the legend series menu, prevents the default action.
export function isResultMenuContextMenu(event: MouseEvent<HTMLElement>): boolean {
    const target = event.target as Element
    return (
        !event.defaultPrevented && event.currentTarget.contains(target) && !target.closest(NATIVE_CONTEXT_MENU_SELECTOR)
    )
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
    if ((event.target as Element).closest(NO_REPLAY_SELECTOR)) {
        return
    }
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
