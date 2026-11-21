// Types of `Heatmap`. Shared types it uses, declared in core.d.ts: ChartTheme, ChartMargins, TooltipContext, Series, SeriesType.
// Generated from @posthog/quill-charts 0.3.0-beta.33, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': Heatmap, HeatmapProps, HeatmapConfig, HeatmapTooltipContext, HeatmapCellDatum, HeatmapBrushData, HeatmapColorScale, HeatmapCellLabelFormatter, HeatmapCellStyle, HeatmapRowMeta.
// Other declarations here are shapes to match, not names to import.

export declare function Heatmap({ onError, ...rest }: HeatmapProps): React.ReactElement

export interface HeatmapProps {
    /** Column labels, left to right. */
    xLabels: string[]
    /** Row labels, bottom to top — `yLabels[0]` is the bottom row (smallest bucket). */
    yLabels: string[]
    /** Dense grid of counts: `cells[rowIndex][colIndex]`, aligned with `yLabels`/`xLabels`.
     *  0 (or a missing entry) means an empty cell — nothing is drawn there. */
    cells: number[][]
    /** Defaults to the nearest `ChartThemeProvider`, then the quill CSS vars. */
    theme?: ChartTheme
    config?: HeatmapConfig
    /** Custom tooltip. Each `ctx.seriesData` entry is one row at the hovered column; narrow to
     *  the hovered cell via `findClosestSeriesKey(ctx.seriesData, ctx.hoverPosition.y)`. */
    tooltip?: (ctx: HeatmapTooltipContext) => React.ReactNode
    /** Fired when the user clicks a cell. */
    onCellClick?: (cell: HeatmapCellDatum) => void
    /** Enables the 2D brush: drag a rectangle to select a column range and a row range at once.
     *  A near-horizontal drag (under ~8px of vertical travel) selects every row, so a sloppy
     *  time-range drag doesn't pin the selection to one bucket sliver. */
    onBrush?: (selection: HeatmapBrushData) => void
    className?: string
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export interface HeatmapConfig {
    /** Custom x-axis tick label formatter. Return null to skip a tick. Called with (label, index). */
    xTickFormatter?: (label: string, index: number) => string | null
    /** How counts map to color intensity. Defaults to 'auto', which picks 'log' or 'linear' from the data. */
    colorScale?: HeatmapColorScale
    /** Accent color for the density ramp (hex, rgb, or var(--…)). Defaults to the first theme
     *  palette color. */
    color?: string
    xAxisLabel?: string
    yAxisLabel?: string
    hideXAxis?: boolean
    hideYAxis?: boolean
    /** Draws a label in the middle of each cell, so the grid reads as values and not only as
     *  density. Called for every cell, empty ones included; return null or an empty string to
     *  leave a cell unlabelled. A label is dropped when its cell is too small for the text, so a
     *  dense grid falls back to a plain density map. Should be referentially stable. */
    cellLabel?: HeatmapCellLabelFormatter
    /** Overrides the appearance of single cells: a second accent for a summary row, a dashed
     *  outline for a period still in progress. Called for every cell; return null for the
     *  default fill. Should be referentially stable. */
    cellStyle?: (cell: HeatmapCellDatum) => HeatmapCellStyle | null
    /** Column indices drawn with a band behind their cells, for a column the consumer selected
     *  or is hovering. */
    highlightedColumns?: number[]
    /** Per-side margin overrides. */
    margins?: Partial<ChartMargins>
    tooltip?: {
        /** Show the single-cell tooltip on hover. Defaults to true. */
        enabled?: boolean
        /** Formats the column (x) label in the tooltip header. */
        labelFormatter?: (label: string) => React.ReactNode
        /** Formats the cell count. Defaults to `toLocaleString`. */
        valueFormatter?: (value: number) => React.ReactNode
    }
}

/** Tooltip context handed to consumer-supplied `tooltip` callbacks — `TooltipContext` with
 *  the row meta baked in. Each `seriesData` entry is one row at the hovered column; use
 *  `findClosestSeriesKey(ctx.seriesData, ctx.hoverPosition.y)` (as the built-in tooltip does)
 *  to narrow to the single hovered cell. */
export type HeatmapTooltipContext = TooltipContext<HeatmapRowMeta>

export interface HeatmapCellDatum {
    /** Column index into `xLabels`. */
    xIndex: number
    /** Row index into `yLabels` (0 = bottom row). */
    yIndex: number
    xLabel: string
    yLabel: string
    /** The cell's count. */
    value: number
}

/** Inclusive index ranges of a completed 2D brush, in grid coordinates. */
export interface HeatmapBrushData {
    /** Column range into `xLabels`. */
    x: {
        startIndex: number
        endIndex: number
    }
    /** Row range into `yLabels` (0 = bottom row). */
    y: {
        startIndex: number
        endIndex: number
    }
}

/** How cell counts map to color intensity: `log` (log1p) for a long-tailed grid such as latency, `linear` for an
 *  even grid such as activity by day and hour, and `auto` (default) to pick one from the data. */
export type HeatmapColorScale = 'auto' | 'log' | 'linear'

/** Returning null or an empty string leaves the cell unlabelled. */
export type HeatmapCellLabelFormatter = (cell: HeatmapCellDatum) => string | null

/** Per-cell appearance override. */
export interface HeatmapCellStyle {
    /** Accent this cell's density fill ramps from, instead of the chart accent. Resolved for
     *  `var(--…)` like `config.color` is. */
    color?: string
    /** Draw a dashed outline and no fill, for a cell whose value is not final yet. */
    outlined?: boolean
    /** Fill the cell at the lightest step when its value is 0. Use it for a cell with a real zero,
     *  so that it reads apart from a cell that has no data. */
    filled?: boolean
}

/** Meta attached to the adapter series the Heatmap hands to the base `Chart` — one series
 *  per row, carrying its row index so tooltip/click code can map back to the grid. */
export interface HeatmapRowMeta {
    rowIndex: number
}
