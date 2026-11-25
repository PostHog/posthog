import { contentRows, dropIntoGrid, settleGrid } from '../grid/gridTiles'
import { bottomOf } from '../grid/placeTiles'
import { type PresentationEdit, applyPresentationEdit } from '../presentation/presentationEdits'
import { linkTabSchema } from './dashboardSchema'
import {
    type Dashboard,
    GRID,
    type SectionWidget,
    type SizeOf,
    type Tile,
    type TilePlace,
    type Widget,
    gridTabs,
    isGridTab,
    isSection,
    isSectionWidget,
    widgetSize,
} from './dashboardTypes'
import { allTiles, changeTileEverywhere, findTile } from './tileTree'

export type LayoutEdit =
    /** `resized` names the tile a person resized, so a section keeps the height they chose. */
    | { edit: 'placeTiles'; grid: string; places: Record<string, TilePlace>; resized?: string }
    | { edit: 'moveTile'; id: string; grid: string; x?: number; y?: number }
    | { edit: 'addTile'; grid: string; widget: Widget }
    | { edit: 'removeTile'; id: string }
    | { edit: 'updateSection'; id: string; patch: Partial<Pick<SectionWidget, 'title'>> }
    /** With `href`, the new tab is a link elsewhere and holds no tiles. */
    | { edit: 'addTab'; title: string; href?: string }
    | { edit: 'renameTab'; id: string; title: string }
    | { edit: 'removeTab'; id: string }
    /** `before` is the tab it lands in front of; null puts it last. */
    | { edit: 'moveTab'; id: string; before: string | null }

/** Edits to what a tile holds. A widget type sends these from its own menu actions, such as a chart switching kind. */
export type ContentEdit = { edit: 'setWidgetConfig'; id: string; config: unknown }

export type DashboardEdit = LayoutEdit | ContentEdit | PresentationEdit

/** The dashboard as one person sees it, with sections they opened or closed for themselves. Never saved. */
export function withFolds(dashboard: Dashboard, folds: Record<string, boolean>, sizeOf: SizeOf): Dashboard {
    const ids = Object.keys(folds)
    if (ids.length === 0) {
        return dashboard
    }
    const folded = ids.reduce(
        (next, id) =>
            changeTileEverywhere(next, id, (tile) =>
                isSection(tile) ? { ...tile, widget: { ...tile.widget, collapsed: folds[id] } } : tile
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
    return section && isSection(section) ? { tiles: section.widget.tiles, cols: section.place.w } : null
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
        isSection(tile) ? { ...tile, widget: { ...tile.widget, tiles: change(tile.widget.tiles) } } : tile
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

function addTile(dashboard: Dashboard, edit: Extract<DashboardEdit, { edit: 'addTile' }>, sizeOf: SizeOf): Dashboard {
    const target = findGrid(dashboard, edit.grid)
    if (!target) {
        return dashboard
    }
    const size = widgetSize(edit.widget, sizeOf)
    const tile: Tile = {
        id: newId(dashboard, isSectionWidget(edit.widget) ? 'section' : 'tile'),
        widget: edit.widget,
        // New tiles go on a new row at the bottom, so adding one never moves or resizes what is there.
        place: {
            x: 0,
            y: bottomOf(target.tiles.map((other) => other.place)),
            w: Math.min(size.w, target.cols),
            h: size.h,
        },
    }
    return changeGrid(dashboard, edit.grid, (tiles) => [...tiles, tile])
}

function applyOnce(dashboard: Dashboard, edit: DashboardEdit, view: View, sizeOf: SizeOf): Dashboard {
    switch (edit.edit) {
        case 'placeTiles': {
            // A section the person opened for themselves is resized open, whatever the saved fold says.
            const shown = edit.resized ? findTile(view(dashboard), edit.resized) : null
            const shownCollapsed = shown && isSection(shown) ? shown.widget.collapsed : undefined
            return changeGrid(dashboard, edit.grid, (tiles) =>
                tiles.map((tile) => {
                    const place = edit.places[tile.id]
                    if (!place) {
                        return tile
                    }
                    if (edit.resized !== tile.id || !isSection(tile) || (shownCollapsed ?? tile.widget.collapsed)) {
                        return { ...tile, place }
                    }
                    // A section resized taller than its tiles need keeps that height. Resized back down to what they
                    // need, it goes back to following its tiles.
                    const minRows = place.h > contentRows(tile.widget) ? place.h : undefined
                    const { minRows: _previous, ...widget } = tile.widget
                    return { ...tile, place, widget: minRows ? { ...widget, minRows } : widget }
                })
            )
        }
        case 'moveTile':
            return moveTile(dashboard, edit, view, sizeOf)
        case 'addTile':
            return addTile(dashboard, edit, sizeOf)
        case 'removeTile':
            return changeTileEverywhere(dashboard, edit.id, () => null)
        case 'setWidgetConfig':
            return changeTileEverywhere(dashboard, edit.id, (tile) => {
                if (isSection(tile)) {
                    return tile
                }
                // A new config can need a bigger tile, such as a stat switched to a line chart.
                const widget = { ...tile.widget, config: edit.config }
                const { minW, minH } = widgetSize(widget, sizeOf)
                const place = { ...tile.place, w: Math.max(tile.place.w, minW), h: Math.max(tile.place.h, minH) }
                return { ...tile, widget, place }
            })
        case 'updateSection':
            return changeTileEverywhere(dashboard, edit.id, (tile) =>
                isSection(tile) ? { ...tile, widget: { ...tile.widget, ...edit.patch } } : tile
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
