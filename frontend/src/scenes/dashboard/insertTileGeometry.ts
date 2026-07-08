// Pure geometry for the inline tile-insert overlay. Kept free of React so it can be unit-tested:
// the line clipping and drop-zone rules here are exactly where the visual bugs lived, and they're
// cheap to pin down with a table of cases.

export interface LineSegment {
    left: number
    width: number
}

export interface TileRect {
    top: number
    bottom: number
    left: number
    right: number
}

/**
 * A column span where dropping a tile lands it at the line: above a tile whose top is on the line
 * (push that tile down) or below a tile whose bottom is on the line (append under it). Over these,
 * insertion stays column-aware; elsewhere in the gap it falls back to a full-width tile at the line.
 */
export interface InsertZone {
    left: number
    right: number
    targetX: number
    targetY: number
}

export interface InsertBoundary {
    lineY: number
    gridRow: number
    segments: LineSegment[]
    zones: InsertZone[]
}

export interface GridGeometry {
    gridWidth: number
    cols: number
    marginX: number
    marginY: number
    rowHeight: number
}

// Tile tops within this many px are treated as the same row (sub-pixel rounding from getBoundingClientRect).
const EDGE_MERGE_PX = 4

// The full width minus any rendered tile the line's pixel passes through, so the line reads as passing
// behind the cards instead of slicing across them. Covered spans are padded into the column gutter so
// the line doesn't peek through the margin right next to a covered tile.
export function computeSegments(
    lineY: number,
    tileRects: TileRect[],
    gridWidth: number,
    marginX: number
): LineSegment[] {
    const covered = tileRects
        .filter((rect) => rect.top < lineY && rect.bottom > lineY)
        .map(
            (rect) =>
                [Math.max(0, rect.left - marginX / 2), Math.min(gridWidth, rect.right + marginX / 2)] as [
                    number,
                    number,
                ]
        )
        .sort((a, b) => a[0] - b[0])

    const merged: Array<[number, number]> = []
    for (const interval of covered) {
        const last = merged[merged.length - 1]
        if (last && interval[0] <= last[1]) {
            last[1] = Math.max(last[1], interval[1])
        } else {
            merged.push([...interval])
        }
    }

    const segments: LineSegment[] = []
    let cursor = 0
    for (const [start, end] of merged) {
        if (start > cursor) {
            segments.push({ left: cursor, width: start - cursor })
        }
        cursor = Math.max(cursor, end)
    }
    if (cursor < gridWidth) {
        segments.push({ left: cursor, width: gridWidth - cursor })
    }
    return segments
}

// Column drop zones for a line: a tile whose top sits on the line (insert above it, pushing it down)
// or whose bottom sits on the line (append directly below). targetY comes from the measured px / row
// unit, exact since react-grid-layout positions tiles at row*unit. Deduped per column + row.
export function computeZones(
    lineY: number,
    tileRects: TileRect[],
    unit: number,
    colUnit: number,
    marginY: number
): InsertZone[] {
    const seen = new Set<string>()
    const zones: InsertZone[] = []
    for (const rect of tileRects) {
        let targetY: number | null = null
        if (Math.abs(rect.top - lineY) <= marginY) {
            targetY = Math.round(rect.top / unit)
        } else if (Math.abs(rect.bottom - lineY) <= marginY) {
            targetY = Math.round(rect.bottom / unit)
        }
        if (targetY === null) {
            continue
        }
        const targetX = Math.round(rect.left / colUnit)
        const key = `${targetX}:${targetY}`
        if (seen.has(key)) {
            continue
        }
        seen.add(key)
        zones.push({ left: rect.left, right: rect.right, targetX, targetY })
    }
    return zones
}

// Insert boundaries derived from the rendered tiles: a line above each distinct tile-top (the gap
// before it) plus one below the lowest tile. The very top edge is skipped — no inserting above the
// board. Each line's grid row is recovered from its pixel position for the actual insert.
export function computeBoundaries(tileRects: TileRect[], geometry: GridGeometry): InsertBoundary[] {
    if (!tileRects.length) {
        return []
    }
    const { gridWidth, cols, marginX, marginY, rowHeight } = geometry
    const unit = rowHeight + marginY
    const colUnit = (gridWidth - marginX * (cols - 1)) / cols + marginX
    const minTop = Math.min(...tileRects.map((r) => r.top))
    const maxBottom = Math.max(...tileRects.map((r) => r.bottom))

    // Distinct tile-top edges (rounded to merge tiles that share a row), excluding the first row.
    const edges = new Map<number, number>()
    for (const rect of tileRects) {
        if (rect.top - minTop < marginY) {
            continue
        }
        edges.set(Math.round(rect.top / EDGE_MERGE_PX) * EDGE_MERGE_PX, rect.top)
    }

    const build = (lineY: number, gridRow: number): InsertBoundary => ({
        lineY,
        gridRow,
        segments: computeSegments(lineY, tileRects, gridWidth, marginX),
        zones: computeZones(lineY, tileRects, unit, colUnit, marginY),
    })

    const result = Array.from(edges.values())
        .sort((a, b) => a - b)
        .map((edge) => build(edge - marginY / 2, Math.round(edge / unit)))
    result.push(build(maxBottom + marginY / 2, Math.round(maxBottom / unit)))
    return result
}
