import { dimColor, resolveCssColor } from '../../core/color-utils'
import type { HeatmapCellDatum, HeatmapCellStyle } from './Heatmap'
import { cellRect, type CellRect, type HeatmapLayout } from './heatmap-layout'

/** Resolved `cellStyle` output, row-major like the grid. A null entry means the default fill. */
export type HeatmapResolvedCellStyles = (HeatmapCellStyle | null)[][]

// Band behind a selected or hovered column. Faint, because it sits under the cells.
const COLUMN_HIGHLIGHT_ALPHA = 0.08
// Dashed border of a cell whose value is not final. Matches the fill's lightest step, so an
// outlined cell reads as the same family as a nearly-empty one.
const OUTLINE_ALPHA = 0.5
const OUTLINE_DASH: readonly number[] = [3, 3]

export interface ResolveCellStylesArgs {
    cellStyle: ((cell: HeatmapCellDatum) => HeatmapCellStyle | null) | undefined
    grid: number[][]
    xLabels: string[]
    yLabels: string[]
}

/** Run the consumer's `cellStyle` over the whole grid once, resolving each `var(--…)` accent to a
 *  concrete color. The canvas cannot resolve a CSS variable, and the draw loop must not call back
 *  into consumer code. */
export function resolveCellStyles({
    cellStyle,
    grid,
    xLabels,
    yLabels,
}: ResolveCellStylesArgs): HeatmapResolvedCellStyles {
    if (!cellStyle) {
        return []
    }
    return yLabels.map((yLabel, yIndex) =>
        xLabels.map((xLabel, xIndex) => {
            const style = cellStyle({ xIndex, yIndex, xLabel, yLabel, value: grid[yIndex]?.[xIndex] ?? 0 })
            if (!style) {
                return null
            }
            return style.color ? { ...style, color: resolveCssColor(style.color) } : style
        })
    )
}

export function drawColumnHighlights(
    ctx: CanvasRenderingContext2D,
    layout: HeatmapLayout,
    columns: number[],
    accent: string
): void {
    if (columns.length === 0) {
        return
    }
    ctx.fillStyle = dimColor(accent, COLUMN_HIGHLIGHT_ALPHA)
    for (const column of columns) {
        if (column < 0 || column >= layout.cols) {
            continue
        }
        const rect = cellRect(layout, column, 0)
        ctx.fillRect(rect.x, layout.plotTop, rect.width, layout.plotHeight)
    }
}

export function drawOutlinedCell(ctx: CanvasRenderingContext2D, rect: CellRect, gap: number, accent: string): void {
    ctx.save()
    ctx.strokeStyle = dimColor(accent, OUTLINE_ALPHA)
    ctx.lineWidth = 1
    ctx.setLineDash([...OUTLINE_DASH])
    // The half-pixel inset puts the 1px stroke on a pixel boundary, so it renders crisp.
    ctx.strokeRect(rect.x + gap / 2 + 0.5, rect.y + gap / 2 + 0.5, rect.width - gap - 1, rect.height - gap - 1)
    ctx.restore()
}
