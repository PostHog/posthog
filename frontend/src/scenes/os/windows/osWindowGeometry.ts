export interface OsPoint {
    x: number
    y: number
}

export interface OsSize {
    width: number
    height: number
}

export interface OsBounds extends OsPoint, OsSize {}

export type OsSnapSide = 'left' | 'right'
export type OsSnapZone = OsSnapSide | 'maximize'

export const OS_WINDOW_MIN_SIZE: OsSize = { width: 360, height: 240 }
export const OS_WINDOW_DEFAULT_MAX_SIZE: OsSize = { width: 1280, height: 860 }
export const OS_WINDOW_CASCADE_OFFSET = 32
/** The part of a title bar that stays on the desktop, so a window can always be dragged back. */
export const OS_WINDOW_REACHABLE_EDGE = 160
export const OS_SNAP_EDGE = 16
export const OS_TIDY_GAP = 8

export function centeredBounds(size: OsSize, desktop: OsSize): OsBounds {
    return {
        ...size,
        x: Math.max(0, Math.round((desktop.width - size.width) / 2)),
        y: Math.max(0, Math.round((desktop.height - size.height) / 2)),
    }
}

export function defaultWindowSize(desktop: OsSize): OsSize {
    return {
        width: Math.round(
            Math.max(OS_WINDOW_MIN_SIZE.width, Math.min(desktop.width * 0.8, OS_WINDOW_DEFAULT_MAX_SIZE.width))
        ),
        height: Math.round(
            Math.max(OS_WINDOW_MIN_SIZE.height, Math.min(desktop.height * 0.85, OS_WINDOW_DEFAULT_MAX_SIZE.height))
        ),
    }
}

/**
 * A new window opens down and right of the focused window, like a cascade.
 * When the cascade would push it off the desktop, it opens centered.
 */
export function placeNewWindow(focused: OsBounds | null, desktop: OsSize): OsBounds {
    const size = defaultWindowSize(desktop)
    if (!focused) {
        return centeredBounds(size, desktop)
    }
    const cascaded = { ...size, x: focused.x + OS_WINDOW_CASCADE_OFFSET, y: focused.y + OS_WINDOW_CASCADE_OFFSET }
    const fits = cascaded.x + cascaded.width <= desktop.width && cascaded.y + cascaded.height <= desktop.height
    return fits ? cascaded : centeredBounds(size, desktop)
}

export function clampBounds(bounds: OsBounds, desktop: OsSize): OsBounds {
    const width = Math.max(
        OS_WINDOW_MIN_SIZE.width,
        Math.min(bounds.width, Math.max(desktop.width, OS_WINDOW_MIN_SIZE.width))
    )
    const height = Math.max(
        OS_WINDOW_MIN_SIZE.height,
        Math.min(bounds.height, Math.max(desktop.height, OS_WINDOW_MIN_SIZE.height))
    )
    const minX = OS_WINDOW_REACHABLE_EDGE - width
    const maxX = Math.max(0, desktop.width - OS_WINDOW_REACHABLE_EDGE)
    const maxY = Math.max(0, desktop.height - OS_WINDOW_REACHABLE_EDGE / 2)
    return {
        width: Math.round(width),
        height: Math.round(height),
        x: Math.round(Math.min(Math.max(bounds.x, minX), maxX)),
        y: Math.round(Math.min(Math.max(bounds.y, 0), maxY)),
    }
}

export function maximizedBounds(desktop: OsSize): OsBounds {
    return { x: 0, y: 0, width: desktop.width, height: desktop.height }
}

export function snappedBounds(side: OsSnapSide, desktop: OsSize): OsBounds {
    const width = Math.round(desktop.width / 2)
    return { x: side === 'left' ? 0 : desktop.width - width, y: 0, width, height: desktop.height }
}

export function snapZoneAt(pointer: OsPoint, desktop: OsSize): OsSnapZone | null {
    if (pointer.x <= OS_SNAP_EDGE) {
        return 'left'
    }
    if (pointer.x >= desktop.width - OS_SNAP_EDGE) {
        return 'right'
    }
    if (pointer.y <= OS_SNAP_EDGE / 2) {
        return 'maximize'
    }
    return null
}

export function snapZoneBounds(zone: OsSnapZone, desktop: OsSize): OsBounds {
    return zone === 'maximize' ? maximizedBounds(desktop) : snappedBounds(zone, desktop)
}

/**
 * Splits the desktop into a grid with one cell per window: one window fills the desktop, two sit
 * side by side, four make a 2x2 grid. The last row stretches its cells when it has fewer windows.
 */
export function tidyLayout(count: number, desktop: OsSize, gap: number = OS_TIDY_GAP): OsBounds[] {
    if (count <= 0) {
        return []
    }
    const columns = Math.ceil(Math.sqrt(count))
    const rows = Math.ceil(count / columns)
    const rowHeight = (desktop.height - gap * (rows + 1)) / rows
    const cells: OsBounds[] = []
    for (let row = 0; row < rows; row++) {
        const inRow = row === rows - 1 ? count - columns * (rows - 1) : columns
        const cellWidth = (desktop.width - gap * (inRow + 1)) / inRow
        for (let column = 0; column < inRow; column++) {
            cells.push({
                x: Math.round(gap + column * (cellWidth + gap)),
                y: Math.round(gap + row * (rowHeight + gap)),
                width: Math.round(Math.max(cellWidth, OS_WINDOW_MIN_SIZE.width)),
                height: Math.round(Math.max(rowHeight, OS_WINDOW_MIN_SIZE.height)),
            })
        }
    }
    return cells
}

export type OsResizeEdge = 'left' | 'right' | 'bottom' | 'bottom-left' | 'bottom-right'

/** The bounds after dragging a resize handle by `delta`. The opposite edge stays in place. */
export function resizeBounds(start: OsBounds, edge: OsResizeEdge, delta: OsPoint): OsBounds {
    const next = { ...start }
    if (edge === 'right' || edge === 'bottom-right') {
        next.width = Math.max(OS_WINDOW_MIN_SIZE.width, start.width + delta.x)
    }
    if (edge === 'left' || edge === 'bottom-left') {
        next.width = Math.max(OS_WINDOW_MIN_SIZE.width, start.width - delta.x)
        next.x = start.x + start.width - next.width
    }
    if (edge === 'bottom' || edge === 'bottom-left' || edge === 'bottom-right') {
        next.height = Math.max(OS_WINDOW_MIN_SIZE.height, start.height + delta.y)
    }
    return next
}
