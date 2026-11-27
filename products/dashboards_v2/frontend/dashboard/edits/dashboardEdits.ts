import { type FilterEdit, applyFilterEdit } from '../../filters/filterEdits'
import { arrangeInColumns, contentRows, dropIntoGrid, resizeSection, settleGrid } from '../../grid/layout/gridTiles'
import { bottomOf } from '../../grid/layout/placeTiles'
import { type SizeOf } from '../../panels/core/panelSpec'
import { linkTabSchema } from '../document/dashboardSchema'
import {
    type Dashboard,
    GRID,
    type SectionPanel,
    type Tile,
    type TilePlace,
    type Panel,
    gridTabs,
    isGridTab,
    isSection,
    isSectionPanel,
    panelRef,
    panelSize,
} from '../document/dashboardTypes'
import { allTiles, changeTileEverywhere, changeTilesWhere, findTile } from '../document/tileTree'
import { type PresentationEdit, applyPresentationEdit } from './presentationEdits'

export type LayoutEdit =
    /** `resized` names the tile a person resized, so a section keeps the height they chose. */
    | { edit: 'placeTiles'; grid: string; places: Record<string, TilePlace>; resized?: string }
    | { edit: 'moveTile'; id: string; grid: string; x?: number; y?: number }
    | { edit: 'addTile'; grid: string; panel: Panel }
    | { edit: 'removeTile'; id: string }
    /** Shows the tile's panel on another grid too. Both tiles then share its content, such as a chart's query. */
    | { edit: 'addToGrid'; id: string; grid: string }
    | { edit: 'autoLayout'; grid: string; columns: number }
    | { edit: 'updateSection'; id: string; patch: Partial<Pick<SectionPanel, 'title'>> }
    /** With `href`, the new tab is a link elsewhere and holds no tiles. */
    | { edit: 'addTab'; title: string; href?: string }
    | { edit: 'renameTab'; id: string; title: string }
    | { edit: 'removeTab'; id: string }
    /** `before` is the tab it lands in front of; null puts it last. */
    | { edit: 'moveTab'; id: string; before: string | null }

/** Edits to what a tile holds. A panel type sends these from its own menu actions, such as a chart switching kind. */
export type ContentEdit = { edit: 'setPanelConfig'; id: string; config: unknown }

export type DashboardEdit = LayoutEdit | ContentEdit | PresentationEdit | FilterEdit

/** The dashboard as one person sees it, with sections they opened or closed for themselves. Never saved. */
export function withFolds(dashboard: Dashboard, folds: Record<string, boolean>, sizeOf: SizeOf): Dashboard {
    const ids = Object.keys(folds)
    if (ids.length === 0) {
        return dashboard
    }
    const folded = ids.reduce(
        (next, id) =>
            changeTileEverywhere(next, id, (tile) =>
                isSection(tile) ? { ...tile, panel: { ...tile.panel, collapsed: folds[id] } } : tile
            ),
        dashboard
    )
    return settleDashboard(folded, sizeOf)
}

/**
 * The dashboard without some tiles, for one view and never saved, such as a tile with nothing to show yet. The tiles
 * around them close the gap, and they come back to their saved places when they are shown again. Pass it, with
 * `withFolds`, as the view to `applyEdit`, so an edit made on screen is placed against what the person saw.
 */
export function withoutTiles(dashboard: Dashboard, hiddenIds: string[], sizeOf: SizeOf): Dashboard {
    if (hiddenIds.length === 0) {
        return dashboard
    }
    const hidden = hiddenIds.reduce((next, id) => changeTileEverywhere(next, id, () => null), dashboard)
    return settleDashboard(hidden, sizeOf)
}

export function settleDashboard(dashboard: Dashboard, sizeOf: SizeOf): Dashboard {
    return {
        ...dashboard,
        tabs: dashboard.tabs.map((tab) =>
            isGridTab(tab) ? { ...tab, tiles: settleGrid(tab.tiles, GRID.columns, sizeOf) } : tab
        ),
    }
}

function findGrid(dashboard: Dashboard, gridId: string): { tiles: Tile[]; cols: number } | null {
    const tab = gridTabs(dashboard).find((candidate) => candidate.id === gridId)
    if (tab) {
        return { tiles: tab.tiles, cols: GRID.columns }
    }
    const section = findTile(dashboard, gridId)
    return section && isSection(section) ? { tiles: section.panel.tiles, cols: section.place.w } : null
}

function changeGrid(dashboard: Dashboard, gridId: string, change: (tiles: Tile[]) => Tile[]): Dashboard {
    if (gridTabs(dashboard).some((tab) => tab.id === gridId)) {
        return {
            ...dashboard,
            tabs: dashboard.tabs.map((tab) =>
                tab.id === gridId && isGridTab(tab) ? { ...tab, tiles: change(tab.tiles) } : tab
            ),
        }
    }
    return changeTileEverywhere(dashboard, gridId, (tile) =>
        isSection(tile) ? { ...tile, panel: { ...tile.panel, tiles: change(tile.panel.tiles) } } : tile
    )
}

function newId(dashboard: Dashboard, prefix: string): string {
    const taken = new Set([...dashboard.tabs.map((tab) => tab.id), ...allTiles(dashboard).map((tile) => tile.id)])
    let n = taken.size + 1
    while (taken.has(`${prefix}${n}`)) {
        n++
    }
    return `${prefix}${n}`
}

function moveTile(
    dashboard: Dashboard,
    edit: Extract<DashboardEdit, { edit: 'moveTile' }>,
    view: View,
    sizeOf: SizeOf
): Dashboard {
    const tile = findTile(dashboard, edit.id)
    // A section cannot go inside itself, so the target is looked up once the tile is out of the tree.
    // Settled first, so a section the tile left already has its new height when the drop cell is used.
    const without = settleDashboard(
        changeTileEverywhere(dashboard, edit.id, () => null),
        sizeOf
    )
    // The drop cell is in the grid as the person saw it, folded and fitted, so the tile lands where its preview showed.
    const shown = findGrid(view(without), edit.grid)
    if (!tile || !shown) {
        return dashboard
    }
    const y = edit.y ?? bottomOf(shown.tiles.map((other) => other.place))
    const landed = dropIntoGrid(shown.tiles, shown.cols, tile, edit.x ?? 0, y, sizeOf)
    const places = new Map(landed.map((placed) => [placed.id, placed.place]))
    // Only where each tile sits is saved. Heights stay as saved, and settling makes room for a folded section.
    return changeGrid(without, edit.grid, (tiles) =>
        [...tiles, tile].map((placed) => {
            const place = places.get(placed.id)
            return place ? { ...placed, place: { ...place, h: placed.place.h } } : placed
        })
    )
}

// New tiles go on a new row at the bottom, so adding one never moves or resizes what is there.
function bottomPlace(grid: { tiles: Tile[]; cols: number }, w: number, h: number): TilePlace {
    return { x: 0, y: bottomOf(grid.tiles.map((other) => other.place)), w: Math.min(w, grid.cols), h }
}

// A new config can need a bigger tile, such as a stat switched to a line chart.
function withConfig(tile: Tile, config: unknown, sizeOf: SizeOf): Tile {
    if (isSection(tile)) {
        return tile
    }
    const panel = { ...tile.panel, config }
    const { minW, minH } = panelSize(panel, sizeOf)
    return {
        ...tile,
        panel,
        place: { ...tile.place, w: Math.max(tile.place.w, minW), h: Math.max(tile.place.h, minH) },
    }
}

function addTile(dashboard: Dashboard, edit: Extract<DashboardEdit, { edit: 'addTile' }>, sizeOf: SizeOf): Dashboard {
    const target = findGrid(dashboard, edit.grid)
    if (!target) {
        return dashboard
    }
    const size = panelSize(edit.panel, sizeOf)
    const tile: Tile = {
        id: newId(dashboard, isSectionPanel(edit.panel) ? 'section' : 'tile'),
        panel: edit.panel,
        place: bottomPlace(target, size.w, size.h),
    }
    return changeGrid(dashboard, edit.grid, (tiles) => [...tiles, tile])
}

function newRef(dashboard: Dashboard): string {
    const taken = new Set(allTiles(dashboard).map(panelRef))
    let n = 1
    while (taken.has(`panel${n}`)) {
        n++
    }
    return `panel${n}`
}

function addToGrid(dashboard: Dashboard, edit: Extract<DashboardEdit, { edit: 'addToGrid' }>): Dashboard {
    const tile = findTile(dashboard, edit.id)
    const target = findGrid(dashboard, edit.grid)
    if (!tile || isSectionPanel(tile.panel) || !target) {
        return dashboard
    }
    const panel = { ...tile.panel, ref: tile.panel.ref ?? newRef(dashboard) }
    const shared = changeTileEverywhere(dashboard, edit.id, (original) => ({ ...original, panel }))
    const copy: Tile = {
        id: newId(dashboard, 'tile'),
        panel,
        place: bottomPlace(target, tile.place.w, tile.place.h),
    }
    return changeGrid(shared, edit.grid, (tiles) => [...tiles, copy])
}

function applyOnce(dashboard: Dashboard, edit: DashboardEdit, view: View, sizeOf: SizeOf): Dashboard {
    switch (edit.edit) {
        case 'placeTiles': {
            // A section the person opened for themselves is resized open, whatever the saved fold says.
            const shown = edit.resized ? findTile(view(dashboard), edit.resized) : null
            const shownCollapsed = shown && isSection(shown) ? shown.panel.collapsed : undefined
            return changeGrid(dashboard, edit.grid, (tiles) =>
                tiles.map((placed) => {
                    const place = edit.places[placed.id]
                    if (!place) {
                        return placed
                    }
                    const tile = resizeSection(placed, place.w, sizeOf)
                    if (edit.resized !== tile.id || !isSection(tile) || (shownCollapsed ?? tile.panel.collapsed)) {
                        return { ...tile, place }
                    }
                    // A section resized taller than its tiles need keeps that height. Resized back down to what they
                    // need, it goes back to following its tiles.
                    const minRows = place.h > contentRows(tile.panel) ? place.h : undefined
                    const { minRows: _previous, ...panel } = tile.panel
                    return { ...tile, place, panel: minRows ? { ...panel, minRows } : panel }
                })
            )
        }
        case 'moveTile':
            return moveTile(dashboard, edit, view, sizeOf)
        case 'addTile':
            return addTile(dashboard, edit, sizeOf)
        case 'removeTile':
            return changeTileEverywhere(dashboard, edit.id, () => null)
        case 'addToGrid':
            return addToGrid(dashboard, edit)
        case 'autoLayout': {
            const grid = findGrid(dashboard, edit.grid)
            return grid
                ? changeGrid(dashboard, edit.grid, (tiles) => arrangeInColumns(tiles, grid.cols, edit.columns, sizeOf))
                : dashboard
        }
        case 'setPanelConfig': {
            const edited = findTile(dashboard, edit.id)
            const ref = edited ? panelRef(edited) : undefined
            return changeTilesWhere(
                dashboard,
                (tile) => tile.id === edit.id || (!!ref && panelRef(tile) === ref),
                (tile) => withConfig(tile, edit.config, sizeOf)
            )
        }
        case 'updateSection':
            return changeTileEverywhere(dashboard, edit.id, (tile) =>
                isSection(tile) ? { ...tile, panel: { ...tile.panel, ...edit.patch } } : tile
            )
        case 'addTab':
            // The same check a loaded document gets, so an edit cannot save a link that runs script.
            if (edit.href && !linkTabSchema.shape.href.safeParse(edit.href).success) {
                return dashboard
            }
            return {
                ...dashboard,
                tabs: [
                    ...dashboard.tabs,
                    edit.href
                        ? { id: newId(dashboard, 'tab'), title: edit.title, href: edit.href }
                        : { id: newId(dashboard, 'tab'), title: edit.title, tiles: [] },
                ],
            }
        case 'renameTab':
            return {
                ...dashboard,
                tabs: dashboard.tabs.map((tab) => (tab.id === edit.id ? { ...tab, title: edit.title } : tab)),
            }
        case 'removeTab':
            const rest = dashboard.tabs.filter((tab) => tab.id !== edit.id)
            // The last tab with tiles stays, so the dashboard always has a grid to show.
            if (!rest.some(isGridTab)) {
                return dashboard
            }
            return { ...dashboard, tabs: rest }
        case 'moveTab': {
            const tab = dashboard.tabs.find((candidate) => candidate.id === edit.id)
            if (!tab) {
                return dashboard
            }
            const rest = dashboard.tabs.filter((candidate) => candidate.id !== edit.id)
            const index = edit.before === null ? rest.length : rest.findIndex((other) => other.id === edit.before)
            if (index === -1) {
                return dashboard
            }
            return { ...dashboard, tabs: [...rest.slice(0, index), tab, ...rest.slice(index)] }
        }
        case 'setAllowFilters':
        case 'addFilter':
        case 'removeFilter':
            return applyFilterEdit(dashboard, edit)
        default:
            return applyPresentationEdit(dashboard, edit)
    }
}

/** How the person sees a dashboard, such as `withFolds`. An edit made on screen is placed against that view. */
export type View = (dashboard: Dashboard) => Dashboard

export function applyEdit(
    dashboard: Dashboard,
    edit: DashboardEdit,
    sizeOf: SizeOf,
    view: View = (shown) => shown
): Dashboard {
    return settleDashboard(applyOnce(dashboard, edit, view, sizeOf), sizeOf)
}
