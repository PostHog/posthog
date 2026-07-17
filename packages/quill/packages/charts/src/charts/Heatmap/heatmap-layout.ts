import { dimColor } from '../../core/color-utils'
import type { ChartDimensions } from '../../core/types'

/** How cell counts map to color intensity. `log` (default) uses log1p normalization —
 *  latency/count grids are long-tailed, and a linear ramp washes out everything but the mode. */
export type HeatmapColorScale = 'log' | 'linear'

/** Uniform grid layout of the heatmap plot area. Rows index bottom-to-top: row 0 is the
 *  bottom row, matching an ascending value axis (smallest bucket at the bottom). */
export interface HeatmapLayout {
    cols: number
    rows: number
    colWidth: number
    rowHeight: number
    plotLeft: number
    plotTop: number
    plotWidth: number
    plotHeight: number
}

export function computeHeatmapLayout(dimensions: ChartDimensions, cols: number, rows: number): HeatmapLayout {
    return {
        cols,
        rows,
        colWidth: cols > 0 ? dimensions.plotWidth / cols : 0,
        rowHeight: rows > 0 ? dimensions.plotHeight / rows : 0,
        plotLeft: dimensions.plotLeft,
        plotTop: dimensions.plotTop,
        plotWidth: dimensions.plotWidth,
        plotHeight: dimensions.plotHeight,
    }
}

export interface CellRect {
    x: number
    y: number
    width: number
    height: number
}

/** Pixel rect of the cell at (colIndex, rowIndex). Row 0 is the bottom row. */
export function cellRect(layout: HeatmapLayout, colIndex: number, rowIndex: number): CellRect {
    return {
        x: layout.plotLeft + colIndex * layout.colWidth,
        y: layout.plotTop + layout.plotHeight - (rowIndex + 1) * layout.rowHeight,
        width: layout.colWidth,
        height: layout.rowHeight,
    }
}

/** Row index under a canvas y pixel, or -1 outside the plot. Row 0 is the bottom row. */
export function rowAtY(layout: HeatmapLayout, y: number): number {
    if (layout.rows === 0 || layout.rowHeight <= 0) {
        return -1
    }
    const row = Math.floor((layout.plotTop + layout.plotHeight - y) / layout.rowHeight)
    return row >= 0 && row < layout.rows ? row : -1
}

/** Like `rowAtY`, but pixels beyond the plot clamp to the edge rows — for gestures (brush
 *  releases) that legitimately end outside the plot area. */
export function rowAtYClamped(layout: HeatmapLayout, y: number): number {
    if (layout.rows === 0 || layout.rowHeight <= 0) {
        return -1
    }
    const row = Math.floor((layout.plotTop + layout.plotHeight - y) / layout.rowHeight)
    return Math.max(0, Math.min(layout.rows - 1, row))
}

export function maxCellValue(cells: number[][]): number {
    let max = 0
    for (const row of cells) {
        for (const value of row) {
            if (Number.isFinite(value) && value > max) {
                max = value
            }
        }
    }
    return max
}

/** Normalize a count to [0, 1] against the grid maximum. Zero/absent counts and an
 *  all-zero grid map to 0 — callers skip drawing those cells entirely. */
export function normalizeCount(count: number, max: number, scale: HeatmapColorScale): number {
    if (!(max > 0) || !(count > 0)) {
        return 0
    }
    const t = scale === 'linear' ? count / max : Math.log1p(count) / Math.log1p(max)
    return Math.max(0, Math.min(1, t))
}

// Alpha floor so a count-of-1 cell is still visible against the plot background.
const MIN_CELL_ALPHA = 0.15

/** Cell fill for a normalized intensity: an alpha ramp over the accent color, so density
 *  reads correctly on light and dark backgrounds without extra theme tokens. */
export function heatmapCellColor(accent: string, t: number): string {
    return dimColor(accent, MIN_CELL_ALPHA + (1 - MIN_CELL_ALPHA) * Math.max(0, Math.min(1, t)))
}
