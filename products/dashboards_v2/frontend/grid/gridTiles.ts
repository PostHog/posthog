import {
    type SectionTile,
    type SectionWidget,
    type SizeOf,
    type Tile,
    GRID,
    isSection,
    widgetSize,
} from '../dashboard/dashboardTypes'
import { type PlacedItem, bottomOf, placeTiles } from './placeTiles'

function minWidthOf(tile: Tile, sizeOf: SizeOf): number {
    const { minW } = widgetSize(tile.widget, sizeOf)
    if (!isSection(tile)) {
        return minW
    }
    return Math.max(minW, ...tile.widget.tiles.map((inner) => inner.place.x + inner.place.w))
}

export function toPlacedItems(tiles: Tile[], sizeOf: SizeOf): PlacedItem[] {
    return tiles.map((tile) => ({ i: tile.id, ...tile.place, minW: minWidthOf(tile, sizeOf) }))
}

function withPlaces(tiles: Tile[], placed: PlacedItem[]): Tile[] {
    const byId = new Map(placed.map((item) => [item.i, item]))
    return tiles.map((tile) => {
        const item = byId.get(tile.id)
        return item ? { ...tile, place: { x: item.x, y: item.y, w: item.w, h: item.h } } : tile
    })
}

export function withSectionRows(tiles: Tile[], cols: number, rows: Record<string, number>, sizeOf: SizeOf): Tile[] {
    if (Object.keys(rows).length === 0) {
        return tiles
    }
    const sized = tiles.map((tile) => (rows[tile.id] ? { ...tile, place: { ...tile.place, h: rows[tile.id] } } : tile))
    return withPlaces(sized, placeTiles(toPlacedItems(sized, sizeOf), cols))
}

function sectionRows(section: SectionWidget): number {
    if (section.collapsed) {
        return GRID.collapsedSectionRows
    }
    return Math.max(contentRows(section), section.minRows ?? 0)
}

/** The rows an open section needs for its header, its padding and its tiles. It is never shorter than this. */
export function contentRows(section: SectionWidget): number {
    return GRID.sectionChromeRows + Math.max(GRID.emptySectionRows, bottomOf(section.tiles.map((tile) => tile.place)))
}

/** Brings one grid into shape, innermost first because a section's height comes from what is inside it. */
export function settleGrid(tiles: Tile[], cols: number, sizeOf: SizeOf): Tile[] {
    const sized = tiles.map((tile) => {
        const w = Math.max(1, Math.min(cols, tile.place.w))
        if (!isSection(tile)) {
            return { ...tile, place: { ...tile.place, w } }
        }
        const widget = { ...tile.widget, tiles: settleGrid(tile.widget.tiles, w, sizeOf) }
        return { ...tile, widget, place: { ...tile.place, w, h: sectionRows(widget) } }
    })
    return withPlaces(sized, placeTiles(toPlacedItems(sized, sizeOf), cols))
}

/** Every tile full width, one under another in reading order: top to bottom, then left to right. */
export function stackTiles(tiles: Tile[], cols: number, sizeOf: SizeOf): Tile[] {
    const ordered = [...tiles].sort((a, b) => a.place.y - b.place.y || a.place.x - b.place.x)
    let y = 0
    return ordered.map((tile) => {
        const stacked = isSection(tile)
            ? stackSection(tile, cols, y, sizeOf)
            : { ...tile, place: { x: 0, y, w: cols, h: stackedRows(tile, sizeOf) } }
        y += stacked.place.h
        return stacked
    })
}

function stackedRows(tile: Tile, sizeOf: SizeOf): number {
    const range = widgetSize(tile.widget, sizeOf).stackedRows
    if (!range) {
        return tile.place.h
    }
    return Math.min(range.max, Math.max(range.min, tile.place.h))
}

function stackSection(tile: SectionTile, cols: number, y: number, sizeOf: SizeOf): Tile {
    const widget = { ...tile.widget, tiles: stackTiles(tile.widget.tiles, cols, sizeOf) }
    return { ...tile, widget, place: { x: 0, y, w: cols, h: sectionRows(widget) } }
}

/**
 * Puts `tile` into a grid at a cell, by the same rules a drag inside that grid follows. The grid shows this
 * result as its preview while a tile from elsewhere hovers over it, so the preview and the drop cannot differ.
 */
export function dropIntoGrid(tiles: Tile[], cols: number, tile: Tile, x: number, y: number, sizeOf: SizeOf): Tile[] {
    const w = Math.min(tile.place.w, cols)
    // A section that lands narrower reflows its own tiles, which changes its height, so the preview uses the result.
    const [sized] = settleGrid([{ ...tile, place: { ...tile.place, w } }], w, sizeOf)
    const dropped = { ...sized, place: { ...sized.place, x: Math.max(0, Math.min(cols - w, x)), y: Math.max(0, y) } }
    const next = [...tiles, dropped]
    const placed = placeTiles(toPlacedItems(next, sizeOf), cols, {
        activeId: tile.id,
        kind: 'drag',
        baseline: toPlacedItems(tiles, sizeOf),
    })
    return withPlaces(next, placed)
}
