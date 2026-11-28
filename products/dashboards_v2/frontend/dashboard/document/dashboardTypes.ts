import type { z } from 'zod'

import type { SavedPanel } from '../../panels/core/panelSchema'
import type { PanelSize, SizeOf } from '../../panels/core/panelSpec'
import type {
    dashboardFilterSchema,
    dashboardDocumentSchema,
    dashboardSchema,
    dashboardTabSchema,
    gridTabSchema,
    linkTabSchema,
    sectionPanelSchema,
    tilePlaceSchema,
    tileSchema,
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

export type DashboardFilter<Config> = Omit<z.infer<typeof dashboardFilterSchema>, 'config'> & { config: Config }

/** A filter as saved. Its `config` is checked against its kind's `configSchema` before the kind's own code uses it. */
export type SavedFilter = DashboardFilter<z.infer<typeof dashboardFilterSchema>['config']>

export type SectionPanel = z.infer<typeof sectionPanelSchema>

export type Panel = SavedPanel | SectionPanel

/** A section's height follows its tiles, so `h` and `minH` only cover a new, empty one. */
export const SECTION_SIZE: PanelSize = { w: 24, h: 6, minW: 8, minH: 3 }

export function isSectionPanel(panel: Panel): panel is SectionPanel {
    return panel.type === 'section'
}

export function panelSize(panel: Panel, sizeOf: SizeOf): PanelSize {
    return isSectionPanel(panel) ? SECTION_SIZE : sizeOf(panel)
}

export type Tile = z.infer<typeof tileSchema>

export type DashboardTab = z.infer<typeof dashboardTabSchema>

export type GridTab = z.infer<typeof gridTabSchema>

export type LinkTab = z.infer<typeof linkTabSchema>

export function isGridTab(tab: DashboardTab): tab is GridTab {
    return 'tiles' in tab
}

/** A valid dashboard has at least one. */
export function gridTabs(dashboard: Dashboard): GridTab[] {
    return dashboard.tabs.filter(isGridTab)
}

/** The tab to show: the one picked if it holds tiles, otherwise the first tab that does. */
export function activeGridTab(dashboard: Dashboard, activeTabId: string | null): GridTab {
    const tabs = gridTabs(dashboard)
    return tabs.find((tab) => tab.id === activeTabId) ?? tabs[0]
}

// An interface rather than an alias, so kea-typegen writes `Dashboard` instead of every field of it.
export interface Dashboard extends z.infer<typeof dashboardSchema> {}

export type DashboardDocument = z.infer<typeof dashboardDocumentSchema>

export type SectionTile = Tile & { panel: SectionPanel }

export function isSection(tile: Tile): tile is SectionTile {
    return isSectionPanel(tile.panel)
}

export function panelRef(tile: Tile): string | undefined {
    return isSectionPanel(tile.panel) ? undefined : tile.panel.ref
}
