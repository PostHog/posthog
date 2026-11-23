import { GRID, columnWidthPx } from './dashboardTypes'

export interface PointerTarget {
    grid: string
    /** Unset for a tab: it has no cells until it is open. */
    x?: number
    y?: number
}

interface DropZone {
    id: string
    element: HTMLElement
    left: number
    top: number
    right: number
    bottom: number
}

export interface DropZones {
    zones: DropZone[]
    anchor: HTMLElement
    anchorLeft: number
    anchorTop: number
}

/**
 * Records where every grid and tab name is, before the drag moves anything.
 * A preview in one grid moves and resizes the grids around it. If the grid under the pointer were read from the
 * page as it is during the drag, the preview could move a grid out from under the pointer, which removes the
 * preview, which moves the grid back, and the landing spot would jump between the two on every move.
 */
export function readDropZones(dragged: HTMLElement): DropZones | null {
    const elements = [...document.querySelectorAll<HTMLElement>('[data-dv2-grid], [data-dv2-tab]')]
    const anchor = elements.find((element) => element.dataset.dv2Grid)
    if (!anchor) {
        return null
    }
    const zones = elements
        .filter((element) => !dragged.contains(element))
        .map((element) => {
            const { left, top, right, bottom } = element.getBoundingClientRect()
            // Below the tab's grid is still the tab's grid, so a tile dragged out under the last section lands in it.
            const zoneBottom = element === anchor ? Infinity : bottom
            return {
                id: (element.dataset.dv2Grid ?? element.dataset.dv2Tab)!,
                element,
                left,
                top,
                right,
                bottom: zoneBottom,
            }
        })
    const { left, top } = anchor.getBoundingClientRect()
    return { zones, anchor, anchorLeft: left, anchorTop: top }
}

export function gridUnderPointer(event: Event, dragged: HTMLElement, recorded: DropZones): PointerTarget | null {
    const { clientX, clientY } = event as MouseEvent
    if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) {
        return null
    }
    // The tab's grid only moves when the page scrolls, so its movement is how far the recorded places have moved.
    const now = recorded.anchor.getBoundingClientRect()
    const x = clientX - (now.left - recorded.anchorLeft)
    const y = clientY - (now.top - recorded.anchorTop)
    // A section's grid comes after the grid that holds it, so the last match is the innermost.
    const zone = recorded.zones.findLast(
        (candidate) => x >= candidate.left && x < candidate.right && y >= candidate.top && y < candidate.bottom
    )
    if (!zone?.element.isConnected) {
        return null
    }
    if (zone.element.dataset.dv2Tab) {
        return { grid: zone.id }
    }
    // The cell is read from the page as it is now, so the landing spot is under the tile as it is drawn.
    const rect = zone.element.getBoundingClientRect()
    const corner = dragged.getBoundingClientRect()
    const columnPitch = columnWidthPx(rect.width, Number(zone.element.dataset.dv2Cols)) + GRID.gapPx
    return {
        grid: zone.id,
        x: Math.max(0, Math.round((corner.left - rect.left) / columnPitch)),
        y: Math.max(0, Math.round((corner.top - rect.top) / (GRID.rowPx + GRID.gapPx))),
    }
}
