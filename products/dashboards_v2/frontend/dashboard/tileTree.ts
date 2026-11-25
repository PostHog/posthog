import { type Dashboard, type Tile, isGridTab, isSection } from './dashboardTypes'

function everyTile(tiles: Tile[]): Tile[] {
    return tiles.flatMap((tile) => (isSection(tile) ? [tile, ...everyTile(tile.widget.tiles)] : [tile]))
}

export function allTiles(dashboard: Dashboard): Tile[] {
    return everyTile(dashboard.tabs.flatMap((tab) => (isGridTab(tab) ? tab.tiles : [])))
}

export function findTile(dashboard: Dashboard, id: string): Tile | null {
    return allTiles(dashboard).find((tile) => tile.id === id) ?? null
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

/** Replaces the tile with this id wherever it sits, at any depth. Returning null removes it. */
export function changeTileEverywhere(dashboard: Dashboard, id: string, change: (tile: Tile) => Tile | null): Dashboard {
    return {
        ...dashboard,
        tabs: dashboard.tabs.map((tab) =>
            isGridTab(tab) ? { ...tab, tiles: changeTile(tab.tiles, id, change) } : tab
        ),
    }
}
