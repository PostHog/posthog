import {
    type Dashboard,
    GRID,
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
    | { edit: 'updateSection'; id: string; patch: Partial<Pick<SectionWidget, 'title' | 'collapsed'>> }
    | { edit: 'addTab'; title: string }
    | { edit: 'renameTab'; id: string; title: string }
    | { edit: 'removeTab'; id: string }

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

/** Every edit ends here, so a saved dashboard never holds an overlap, a gap or a stale section height. */
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
    const dropped = { ...tile, place: { ...tile.place, w, x: Math.max(0, Math.min(cols - w, x)), y: Math.max(0, y) } }
    const next = [...tiles, dropped]
    const placed = placeTiles(toPlacedItems(next), cols, {
        activeId: tile.id,
        kind: 'drag',
        baseline: toPlacedItems(tiles),
    })
    return withPlaces(next, placed)
}

function applyOnce(dashboard: Dashboard, edit: DashboardEdit): Dashboard {
    switch (edit.edit) {
        case 'placeTiles':
            return changeGrid(dashboard, edit.grid, (tiles) =>
                tiles.map((tile) => (edit.places[tile.id] ? { ...tile, place: edit.places[tile.id] } : tile))
            )
        case 'moveTile': {
            const tile = findTile(dashboard, edit.id)
            // A section cannot go inside itself, so the target is looked up once the tile is out of the tree.
            // Settled first, so a section the tile left already has its new height when the drop cell is used.
            const without = settleDashboard(changeTileEverywhere(dashboard, edit.id, () => null))
            const target = findGrid(without, edit.grid)
            if (!tile || !target) {
                return dashboard
            }
            const y = edit.y ?? bottomOf(target.tiles.map((other) => other.place))
            return changeGrid(without, edit.grid, (tiles) => dropIntoGrid(tiles, target.cols, tile, edit.x ?? 0, y))
        }
        case 'addTile': {
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
        case 'removeTile':
            return changeTileEverywhere(dashboard, edit.id, () => null)
        case 'updateSection':
            return changeTileEverywhere(dashboard, edit.id, (tile) =>
                isSection(tile) ? { ...tile, widget: { ...tile.widget, ...edit.patch } } : tile
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
    }
}

export function applyEdit(dashboard: Dashboard, edit: DashboardEdit): Dashboard {
    return settleDashboard(applyOnce(dashboard, edit))
}
