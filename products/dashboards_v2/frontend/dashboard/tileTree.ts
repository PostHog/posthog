import { type Dashboard, type Tile, isGridTab, isSection } from './dashboardTypes'

/** The tiles in a grid and in every section inside it. */
export function everyTile(tiles: Tile[]): Tile[] {
    return tiles.flatMap((tile) => (isSection(tile) ? [tile, ...everyTile(tile.widget.tiles)] : [tile]))
}

export function allTiles(dashboard: Dashboard): Tile[] {
    return everyTile(dashboard.tabs.flatMap((tab) => (isGridTab(tab) ? tab.tiles : [])))
}

export function findTile(dashboard: Dashboard, id: string): Tile | null {
    return allTiles(dashboard).find((tile) => tile.id === id) ?? null
}

function changeTiles(tiles: Tile[], matches: (tile: Tile) => boolean, change: (tile: Tile) => Tile | null): Tile[] {
    return tiles.flatMap((tile) => {
        // A matching section's own tiles may match too, so they change first.
        const inner = isSection(tile)
            ? { ...tile, widget: { ...tile.widget, tiles: changeTiles(tile.widget.tiles, matches, change) } }
            : tile
        if (!matches(tile)) {
            return [inner]
        }
        const next = change(inner)
        return next ? [next] : []
    })
}

/** Replaces every matching tile wherever it sits, at any depth. Returning null removes it. */
export function changeTilesWhere(
    dashboard: Dashboard,
    matches: (tile: Tile) => boolean,
    change: (tile: Tile) => Tile | null
): Dashboard {
    return {
        ...dashboard,
        tabs: dashboard.tabs.map((tab) =>
            isGridTab(tab) ? { ...tab, tiles: changeTiles(tab.tiles, matches, change) } : tab
        ),
    }
}

export function changeTileEverywhere(dashboard: Dashboard, id: string, change: (tile: Tile) => Tile | null): Dashboard {
    return changeTilesWhere(dashboard, (tile) => tile.id === id, change)
}
