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
    // Narrowing a section scales its tiles down, so it is only as narrow as its narrowest-allowed tile.
    return Math.max(minW, ...tile.widget.tiles.map((inner) => minWidthOf(inner, sizeOf)))
}

/** Scales rather than reflows, during a resize and after it, so the tiles land where they were drawn. */
export function resizeSection(tile: Tile, w: number, sizeOf: SizeOf): Tile {
    if (!isSection(tile) || tile.place.w === w) {
        return tile
    }
    const tiles = settleGrid(scaleTiles(tile.widget.tiles, tile.place.w, w, sizeOf), w, sizeOf)
    return { ...tile, place: { ...tile.place, w }, widget: { ...tile.widget, tiles } }
}

function scaleTiles(tiles: Tile[], from: number, to: number, sizeOf: SizeOf): Tile[] {
    if (from === to) {
        return tiles
    }
    return tiles.map((tile) => {
        const x = Math.round((tile.place.x * to) / from)
        const right = Math.round(((tile.place.x + tile.place.w) * to) / from)
        const w = Math.min(to, Math.max(right - x, minWidthOf(tile, sizeOf), 1))
        const scaled = { ...tile, place: { ...tile.place, x: Math.min(x, to - w), w } }
        if (!isSection(tile)) {
            return scaled
        }
        return { ...scaled, widget: { ...tile.widget, tiles: scaleTiles(tile.widget.tiles, tile.place.w, w, sizeOf) } }
    })
}

export function inReadingOrder(tiles: Tile[]): Tile[] {
    return [...tiles].sort((a, b) => a.place.y - b.place.y || a.place.x - b.place.x)
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

/** A tile wider than its column keeps its minimum width, and settling moves what it overlaps down. */
export function arrangeInColumns(tiles: Tile[], cols: number, columns: number, sizeOf: SizeOf): Tile[] {
    const count = Math.max(1, Math.min(columns, cols))
    const widths = Array.from(
        { length: count },
        (_, index) => Math.floor(cols / count) + (index < cols % count ? 1 : 0)
    )
    const ordered = inReadingOrder(tiles)
    let y = 0
    let rowHeight = 0
    return ordered.map((tile, index) => {
        const column = index % count
        if (column === 0) {
            y += rowHeight
            rowHeight = 0
        }
        rowHeight = Math.max(rowHeight, tile.place.h)
        const w = Math.min(cols, Math.max(widths[column], minWidthOf(tile, sizeOf)))
        const x = Math.min(
            cols - w,
            widths.slice(0, column).reduce((sum, width) => sum + width, 0)
        )
        return { ...tile, place: { x, y, w, h: tile.place.h } }
    })
}

/** Every tile full width, one under another in reading order: top to bottom, then left to right. */
export function stackTiles(tiles: Tile[], cols: number, sizeOf: SizeOf): Tile[] {
    const ordered = inReadingOrder(tiles)
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
