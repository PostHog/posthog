/** A point in the viewport, in CSS pixels. */
export interface TodayTourPoint {
    x: number
    y: number
}

export function centerOf(element: Element): TodayTourPoint {
    const rect = element.getBoundingClientRect()
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
}

/** Where a click happened. A keyboard press has no pointer position, so it counts as the center of the element. */
export function clickPoint(event: React.MouseEvent<HTMLElement>): TodayTourPoint {
    return event.detail > 0 ? { x: event.clientX, y: event.clientY } : centerOf(event.currentTarget)
}
