import type { AccessControlLevel } from '~/types'

export const GRID = {
    columns: 24,
    rowPx: 32,
    /** Rows an open section keeps for its tiles when it has none, so it can still take a drop. */
    emptySectionRows: 2,
    /** Below this width every tile is full width and the layout is read-only, because drag and resize need room. */
    stackBelowPx: 768,
} as const

/** Space between tiles, across and down. The names and sizes match the tile density of v1 dashboards. */
export type TileSpacing = 'tight' | 'compact' | 'standard'

export const TILE_SPACING_GAP_PX: Record<TileSpacing, number> = { tight: 8, compact: 12, standard: 16 }

export const TILE_SPACING_LABELS: Record<TileSpacing, string> = {
    tight: 'Tight',
    compact: 'Compact',
    standard: 'Standard',
}

export function gapPxOf(dashboard: Dashboard): number {
    return TILE_SPACING_GAP_PX[dashboard.appearance?.tileSpacing ?? 'compact']
}

export function columnWidthPx(width: number, cols: number, gapPx: number): number {
    return (width - gapPx * (cols - 1)) / cols
}

export function spanPx(cells: number, cellPx: number, gapPx: number): number {
    return cells * cellPx + (cells - 1) * gapPx
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
    footer?: ContentWidgetFooter
    /** Which parts of the tile show. A part that is missing shows. */
    parts?: ContentWidgetParts
}

export interface ContentWidgetParts {
    header?: boolean
    description?: boolean
    footer?: boolean
}

export interface ContentWidgetFooter {
    text?: string
    showUpdatedAt?: boolean
    link?: { label: string; url: string }
}

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
    /** How the whole dashboard looks. Every tile on every tab follows it. */
    appearance?: DashboardAppearance
    tabs: DashboardTab[]
}

export interface DashboardAppearance {
    tileSpacing?: TileSpacing
}

export type SectionTile = Tile & { widget: SectionWidget }

export function isSection(tile: Tile): tile is SectionTile {
    return tile.widget.type === 'section'
}

/** Whether a content tile shows a part. The description lives in the header, so hiding the header hides it too. */
export function showsPart(widget: ContentWidget, part: keyof ContentWidgetParts): boolean {
    if (part === 'description' && widget.parts?.header === false) {
        return false
    }
    return widget.parts?.[part] !== false
}
