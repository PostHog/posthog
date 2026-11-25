import type { z } from 'zod'

import type {
    contentWidgetPartsSchema,
    contentWidgetSchema,
    dashboardSchema,
    dashboardTabSchema,
    gridTabSchema,
    linkTabSchema,
    sectionWidgetSchema,
    tilePlaceSchema,
    tileSchema,
    timeRangeSchema,
} from './dashboardSchema'

export const GRID = {
    columns: 24,
    /** Small, so heights can be set finely: a row and a gap make one 22px step. */
    rowPx: 10,
    gapPx: 12,
    /** Rows an open section keeps for its tiles when it has none, so it can still take a drop. */
    emptySectionRows: 4,
    /** A closed section is a quill card with only its header (44px), which fits in three rows (54px). */
    collapsedSectionRows: 3,
    /**
     * Rows an open section adds around its tiles: three rows (66px) hold its 44px card header and 11px of padding
     * above and below the tiles.
     */
    sectionChromeRows: 3,
    /** Space between a section card's edges and its tiles, in pixels, the same on every side. */
    sectionInsetPx: 11,
    /** Below this width every tile is full width and the layout is read-only, because drag and resize need room. */
    stackBelowPx: 768,
} as const

export function columnWidthPx(width: number, cols: number): number {
    return (width - GRID.gapPx * (cols - 1)) / cols
}

export function spanPx(cells: number, cellPx: number): number {
    return cells * cellPx + (cells - 1) * GRID.gapPx
}

export type TilePlace = z.infer<typeof tilePlaceSchema>

export type TimeRange = z.infer<typeof timeRangeSchema>

export type ContentWidgetParts = z.infer<typeof contentWidgetPartsSchema>

export interface WidgetSize {
    w: number
    h: number
    minW: number
    minH: number
    /** A chart sized for a wide screen would fill a phone, so a stacked chart stays between these heights. */
    stackedRows?: { min: number; max: number }
}

/** A tile's content. `Config` is the widget type's own config, which its spec declares. */
export type ContentWidget<Config = unknown> = Omit<z.infer<typeof contentWidgetSchema>, 'config'> & { config: Config }

export type SectionWidget = z.infer<typeof sectionWidgetSchema>

export type Widget = ContentWidget | SectionWidget

/** A section's height follows its tiles, so `h` and `minH` only cover a new, empty one. */
export const SECTION_SIZE: WidgetSize = { w: 24, h: 6, minW: 4, minH: 3 }

/** Looks up a content widget's size. Layout code takes it as an argument, so it never imports a widget. */
export type SizeOf = (widget: ContentWidget) => WidgetSize

export function isSectionWidget(widget: Widget): widget is SectionWidget {
    return widget.type === 'section'
}

export function widgetSize(widget: Widget, sizeOf: SizeOf): WidgetSize {
    return isSectionWidget(widget) ? SECTION_SIZE : sizeOf(widget)
}

export type Tile = z.infer<typeof tileSchema>

export type DashboardTab = z.infer<typeof dashboardTabSchema>

export type GridTab = z.infer<typeof gridTabSchema>

export type LinkTab = z.infer<typeof linkTabSchema>

export function isGridTab(tab: DashboardTab): tab is GridTab {
    return 'tiles' in tab
}

/** The tabs that hold tiles. A valid dashboard has at least one. */
export function gridTabs(dashboard: Dashboard): GridTab[] {
    return dashboard.tabs.filter(isGridTab)
}

/** The tab to show: the one picked if it holds tiles, otherwise the first tab that does. */
export function activeGridTab(dashboard: Dashboard, activeTabId: string | null): GridTab {
    const tabs = gridTabs(dashboard)
    return tabs.find((tab) => tab.id === activeTabId) ?? tabs[0]
}

export type Dashboard = z.infer<typeof dashboardSchema>

export type SectionTile = Tile & { widget: SectionWidget }

export function isSection(tile: Tile): tile is SectionTile {
    return isSectionWidget(tile.widget)
}
