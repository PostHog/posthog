import {
    type ContentWidgetParts,
    type Dashboard,
    GRID,
    type SectionTile,
    type SectionWidget,
    type Tile,
    type TilePlace,
    type Widget,
    isSection,
} from './dashboardTypes'
import { type PlacedItem, bottomOf, placeTiles } from './placeTiles'
import { widgetSize } from './widgetSizes'

export type DashboardEdit =
    | { edit: 'placeTiles'; grid: string; places: Record<string, TilePlace> }
    | { edit: 'moveTile'; id: string; grid: string; x?: number; y?: number }
    | { edit: 'addTile'; grid: string; widget: Widget }
    | { edit: 'removeTile'; id: string }
    | { edit: 'updateSection'; id: string; patch: Partial<Pick<SectionWidget, 'title'>> }
    | { edit: 'setTileParts'; id: string; parts: ContentWidgetParts }
    | { edit: 'addTab'; title: string }
    | { edit: 'renameTab'; id: string; title: string }
    | { edit: 'removeTab'; id: string }
    /** `before` is the tab it lands in front of; null puts it last. */
    | { edit: 'moveTab'; id: string; before: string | null }

function minWidthOf(tile: Tile): number {
    if (!isSection(tile)) {
        return widgetSize(tile.widget).minW
    }
    return Math.max(widgetSize(tile.widget).minW, ...tile.widget.tiles.map((inner) => inner.place.x + inner.place.w))
}

export function toPlacedItems(tiles: Tile[]): PlacedItem[] {
    return tiles.map((tile) => ({ i: tile.id, ...tile.place, minW: minWidthOf(tile) }))
}

function withPlaces(tiles: Tile[], placed: PlacedItem[]): Tile[] {
    const byId = new Map(placed.map((item) => [item.i, item]))
    return tiles.map((tile) => {
        const item = byId.get(tile.id)
        return item ? { ...tile, place: { x: item.x, y: item.y, w: item.w, h: item.h } } : tile
    })
}

export function withSectionRows(tiles: Tile[], cols: number, rows: Record<string, number>): Tile[] {
    if (Object.keys(rows).length === 0) {
        return tiles
    }
    const sized = tiles.map((tile) => (rows[tile.id] ? { ...tile, place: { ...tile.place, h: rows[tile.id] } } : tile))
    return withPlaces(sized, placeTiles(toPlacedItems(sized), cols))
}

function sectionRows(section: SectionWidget): number {
    if (section.collapsed) {
        return 1
    }
    return 1 + Math.max(GRID.emptySectionRows, bottomOf(section.tiles.map((tile) => tile.place)))
}

/** Brings one grid into shape, innermost first because a section's height comes from what is inside it. */
function settleGrid(tiles: Tile[], cols: number): Tile[] {
    const sized = tiles.map((tile) => {
        const w = Math.max(1, Math.min(cols, tile.place.w))
        if (!isSection(tile)) {
            return { ...tile, place: { ...tile.place, w } }
        }
        const widget = { ...tile.widget, tiles: settleGrid(tile.widget.tiles, w) }
        return { ...tile, widget, place: { ...tile.place, w, h: sectionRows(widget) } }
    })
    return withPlaces(sized, placeTiles(toPlacedItems(sized), cols))
}

/** Every tile full width, one under another in reading order: top to bottom, then left to right. */
export function stackTiles(tiles: Tile[], cols: number): Tile[] {
    const ordered = [...tiles].sort((a, b) => a.place.y - b.place.y || a.place.x - b.place.x)
    let y = 0
    return ordered.map((tile) => {
        const stacked = isSection(tile)
            ? stackSection(tile, cols, y)
            : { ...tile, place: { x: 0, y, w: cols, h: stackedRows(tile) } }
        y += stacked.place.h
        return stacked
    })
}

function stackedRows(tile: Tile): number {
    const range = widgetSize(tile.widget).stackedRows
    if (!range) {
        return tile.place.h
    }
    return Math.min(range.max, Math.max(range.min, tile.place.h))
}

function stackSection(tile: SectionTile, cols: number, y: number): Tile {
    const widget = { ...tile.widget, tiles: stackTiles(tile.widget.tiles, cols) }
    return { ...tile, widget, place: { x: 0, y, w: cols, h: sectionRows(widget) } }
}

/** The dashboard as one person sees it, with sections they opened or closed for themselves. Never saved. */
export function withFolds(dashboard: Dashboard, folds: Record<string, boolean>): Dashboard {
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
    return settleDashboard(folded)
}

export function settleDashboard(dashboard: Dashboard): Dashboard {
    return { ...dashboard, tabs: dashboard.tabs.map((tab) => ({ ...tab, tiles: settleGrid(tab.tiles, GRID.columns) })) }
}

function everyTile(tiles: Tile[]): Tile[] {
    return tiles.flatMap((tile) => (isSection(tile) ? [tile, ...everyTile(tile.widget.tiles)] : [tile]))
}

export function allTiles(dashboard: Dashboard): Tile[] {
    return everyTile(dashboard.tabs.flatMap((tab) => tab.tiles))
}

export function findTile(dashboard: Dashboard, id: string): Tile | null {
    return allTiles(dashboard).find((tile) => tile.id === id) ?? null
}

function findGrid(dashboard: Dashboard, gridId: string): { tiles: Tile[]; cols: number } | null {
    const tab = dashboard.tabs.find((candidate) => candidate.id === gridId)
    if (tab) {
        return { tiles: tab.tiles, cols: GRID.columns }
    }
    const section = findTile(dashboard, gridId)
    return section && isSection(section) ? { tiles: section.widget.tiles, cols: section.place.w } : null
}

function changeGrid(dashboard: Dashboard, gridId: string, change: (tiles: Tile[]) => Tile[]): Dashboard {
    if (dashboard.tabs.some((tab) => tab.id === gridId)) {
        return {
            ...dashboard,
            tabs: dashboard.tabs.map((tab) => (tab.id === gridId ? { ...tab, tiles: change(tab.tiles) } : tab)),
        }
    }
    return changeTileEverywhere(dashboard, gridId, (tile) =>
        isSection(tile) ? { ...tile, widget: { ...tile.widget, tiles: change(tile.widget.tiles) } } : tile
    )
}

function changeTile(tiles: Tile[], id: string, change: (tile: Tile) => Tile | null): Tile[] {
    return tiles.flatMap((tile) => {
        if (tile.id === id) {
            const next = change(tile)
            return next ? [next] : []
        }
        return isSection(tile)
            ? [{ ...tile, widget: { ...tile.widget, tiles: changeTile(tile.widget.tiles, id, change) } }]
            : [tile]
    })
}

function changeTileEverywhere(dashboard: Dashboard, id: string, change: (tile: Tile) => Tile | null): Dashboard {
    return { ...dashboard, tabs: dashboard.tabs.map((tab) => ({ ...tab, tiles: changeTile(tab.tiles, id, change) })) }
}

function newId(dashboard: Dashboard, prefix: string): string {
    const taken = new Set([...dashboard.tabs.map((tab) => tab.id), ...allTiles(dashboard).map((tile) => tile.id)])
    let n = taken.size + 1
    while (taken.has(`${prefix}${n}`)) {
        n++
    }
    return `${prefix}${n}`
}

/**
 * Puts `tile` into a grid at a cell, by the same rules a drag inside that grid follows. The grid shows this
 * result as its preview while a tile from elsewhere hovers over it, so the preview and the drop cannot differ.
 */
export function dropIntoGrid(tiles: Tile[], cols: number, tile: Tile, x: number, y: number): Tile[] {
    const w = Math.min(tile.place.w, cols)
    // A section that lands narrower reflows its own tiles, which changes its height, so the preview uses the result.
    const [sized] = settleGrid([{ ...tile, place: { ...tile.place, w } }], w)
    const dropped = { ...sized, place: { ...sized.place, x: Math.max(0, Math.min(cols - w, x)), y: Math.max(0, y) } }
    const next = [...tiles, dropped]
    const placed = placeTiles(toPlacedItems(next), cols, {
        activeId: tile.id,
        kind: 'drag',
        baseline: toPlacedItems(tiles),
    })
    return withPlaces(next, placed)
}

function moveTile(dashboard: Dashboard, edit: Extract<DashboardEdit, { edit: 'moveTile' }>, view: View): Dashboard {
    const tile = findTile(dashboard, edit.id)
    // A section cannot go inside itself, so the target is looked up once the tile is out of the tree.
    // Settled first, so a section the tile left already has its new height when the drop cell is used.
    const without = settleDashboard(changeTileEverywhere(dashboard, edit.id, () => null))
    // The drop cell is in the grid as the person saw it, folded and fitted, so the tile lands where its preview showed.
    const shown = findGrid(view(without), edit.grid)
    if (!tile || !shown) {
        return dashboard
    }
    const y = edit.y ?? bottomOf(shown.tiles.map((other) => other.place))
    const landed = dropIntoGrid(shown.tiles, shown.cols, tile, edit.x ?? 0, y)
    const places = new Map(landed.map((placed) => [placed.id, placed.place]))
    // Only where each tile sits is saved. Heights stay as saved, and settling makes room for a folded section.
    return changeGrid(without, edit.grid, (tiles) =>
        [...tiles, tile].map((placed) => {
            const place = places.get(placed.id)
            return place ? { ...placed, place: { ...place, h: placed.place.h } } : placed
        })
    )
}

function addTile(dashboard: Dashboard, edit: Extract<DashboardEdit, { edit: 'addTile' }>): Dashboard {
    const target = findGrid(dashboard, edit.grid)
    if (!target) {
        return dashboard
    }
    const size = widgetSize(edit.widget)
    const tile: Tile = {
        id: newId(dashboard, edit.widget.type === 'section' ? 'section' : 'tile'),
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

function applyOnce(dashboard: Dashboard, edit: DashboardEdit, view: View): Dashboard {
    switch (edit.edit) {
        case 'placeTiles':
            return changeGrid(dashboard, edit.grid, (tiles) =>
                tiles.map((tile) => (edit.places[tile.id] ? { ...tile, place: edit.places[tile.id] } : tile))
            )
        case 'moveTile':
            return moveTile(dashboard, edit, view)
        case 'addTile':
            return addTile(dashboard, edit)
        case 'removeTile':
            return changeTileEverywhere(dashboard, edit.id, () => null)
        case 'updateSection':
            return changeTileEverywhere(dashboard, edit.id, (tile) =>
                isSection(tile) ? { ...tile, widget: { ...tile.widget, ...edit.patch } } : tile
            )
        case 'setTileParts':
            return changeTileEverywhere(dashboard, edit.id, (tile) =>
                isSection(tile) ? tile : { ...tile, widget: { ...tile.widget, parts: edit.parts } }
            )
        case 'addTab':
            return {
                ...dashboard,
                tabs: [...dashboard.tabs, { id: newId(dashboard, 'tab'), title: edit.title, tiles: [] }],
            }
        case 'renameTab':
            return {
                ...dashboard,
                tabs: dashboard.tabs.map((tab) => (tab.id === edit.id ? { ...tab, title: edit.title } : tab)),
            }
        case 'removeTab':
            if (dashboard.tabs.length <= 1) {
                return dashboard
            }
            return { ...dashboard, tabs: dashboard.tabs.filter((tab) => tab.id !== edit.id) }
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
    }
}

/** How the person sees a dashboard, such as `withFolds`. An edit made on screen is placed against that view. */
type View = (dashboard: Dashboard) => Dashboard

export function applyEdit(dashboard: Dashboard, edit: DashboardEdit, view: View = (shown) => shown): Dashboard {
    return settleDashboard(applyOnce(dashboard, edit, view))
}
