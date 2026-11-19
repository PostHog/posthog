import type { AccessControlLevel } from '~/types'

export const GRID = {
    columns: 24,
    rowPx: 32,
    gapPx: 12,
    /** Rows an open section keeps for its tiles when it has none, so it can still take a drop. */
    emptySectionRows: 2,
} as const

export function columnWidthPx(width: number, cols: number): number {
    return (width - GRID.gapPx * (cols - 1)) / cols
}

export function spanPx(cells: number, cellPx: number): number {
    return cells * cellPx + (cells - 1) * GRID.gapPx
}

export interface TilePlace {
    x: number
    y: number
    w: number
    h: number
}

export interface WidgetQuery {
    kind: 'hogql'
    sql: string
}

export interface ContentWidget {
    type: 'stat' | 'line' | 'bar' | 'markdown'
    title?: string
    description?: string
    query?: WidgetQuery
    text?: string
    format?: 'number' | 'currency' | 'percentage'
    /** When the widget's data was last computed, as an ISO timestamp. */
    refreshedAt?: string
    /** The pieces placed in the tile's footer, shown in this order. No pieces means no footer. */
    footer?: TileFooterItem[]
}

export type TileFooterItem =
    | { type: 'text'; text: string }
    | { type: 'updatedAt' }
    | { type: 'link'; label: string; url: string }

/**
 * A grid inside a tile. Its cells line up with the cells of the grid it sits in: one row for the header, then its
 * own tiles. Its height always fits its tiles, so `place.h` of a section tile is worked out, never chosen.
 */
export interface SectionWidget {
    type: 'section'
    title: string
    collapsed?: boolean
    tiles: Tile[]
}

export type Widget = ContentWidget | SectionWidget

export interface Tile {
    id: string
    place: TilePlace
    widget: Widget
}

export interface DashboardTab {
    id: string
    title: string
    tiles: Tile[]
}

export interface Dashboard {
    version: 2
    title: string
    /** The viewer's access to this dashboard, as v1 dashboards carry it. Missing means the project-wide level. */
    user_access_level?: AccessControlLevel
    tabs: DashboardTab[]
}

export type SectionTile = Tile & { widget: SectionWidget }

export function isSection(tile: Tile): tile is SectionTile {
    return tile.widget.type === 'section'
}
