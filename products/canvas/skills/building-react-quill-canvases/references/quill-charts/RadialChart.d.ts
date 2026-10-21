// Types of `RadialChart`. Shared types it uses, declared in core.d.ts: Series, ChartTheme, TooltipContext, RadialSlicePayload, SeriesType, ResolvedSeries.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': RadialChart, RadialChartProps, RadialLayoutBuilder, ChartDrawArgs, PieLayout, ChartDimensions, ChartScales, DragRect, PieSlice, YAxisScale.
// Other declarations here are shapes to match, not names to import.

export declare function RadialChart<Meta = unknown>({
    series,
    theme,
    buildLayout,
    drawStatic,
    drawHover,
    tooltip: renderTooltipProp,
    showTooltip,
    onSliceClick,
    hitOuterSlack,
    hoverAnimationMs,
    className,
    dataAttr,
    children,
}: RadialChartProps<Meta>): React.ReactElement

export interface RadialChartProps<Meta = unknown> {
    series: Series<Meta>[]
    theme: ChartTheme
    buildLayout: RadialLayoutBuilder<Meta>
    drawStatic: (args: ChartDrawArgs) => void
    drawHover: (args: ChartDrawArgs) => DrawHoverResult
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    showTooltip?: boolean
    onSliceClick?: (payload: RadialSlicePayload<Meta>) => void
    /** Slack beyond `outerRadius` for hit-testing — typically the hover pop-out distance. */
    hitOuterSlack?: number
    /** Duration (ms) of the hover-overlay transition. `0` disables (instant pop-out). */
    hoverAnimationMs?: number
    className?: string
    dataAttr?: string
    children?: React.ReactNode
}

/** Builds the geometry — and the matching ChartScales / RadialLayoutContext — from the
 *  current dimensions and resolved series. Pie/Donut variants supply their own builder. */
export type RadialLayoutBuilder<Meta = unknown> = (
    series: ResolvedSeries<Meta>[],
    dimensions: {
        plotLeft: number
        plotTop: number
        plotWidth: number
        plotHeight: number
    }
) => PieLayout<Meta>

/** Arguments passed to a chart type's canvas draw function. */
export interface ChartDrawArgs {
    /** 2D canvas rendering context (DPR already applied, save/restore handled by Chart). */
    ctx: CanvasRenderingContext2D
    /** Layout dimensions of the chart. */
    dimensions: ChartDimensions
    /** Scale functions for mapping data to pixel coordinates. */
    scales: ChartScales
    /** Series with fallback colors already applied. */
    series: ResolvedSeries[]
    /** X-axis labels. */
    labels: string[]
    /** Index of the currently hovered data point, or -1. */
    hoverIndex: number
    /** Cursor position in canvas pixels, or `null` for non-hover redraws (static layer / post-mouseleave). */
    hoverPosition: {
        x: number
        y: number
    } | null
    /** Chart theme colors. */
    theme: ChartTheme
    /** Hover-fade progress (0..1). Apply as `ctx.globalAlpha` around highlight rendering. */
    hoverProgress: number
    /** Restart the hover-fade at progress 0; returns the new value to use this frame.
     *  Call when the chart type detects a visible-state change at the same hoverIndex. */
    resetHoverFade: () => number
    /** Live pixel range of an in-progress selection: x-axis drag-to-zoom, plus the vertical
     *  range on a 2D (`onAreaSelect`) brush. Null when no drag is active. Only the hover
     *  overlay reads this — the static layer ignores it. */
    dragRect?: DragRect | null
}

/** `true` = drew a visible highlight; `false` = nothing visible (freeze the fade timer). */
export type DrawHoverResult = boolean

export interface PieLayout<Meta = unknown> {
    slices: PieSlice<Meta>[]
    total: number
    cx: number
    cy: number
    /** Outer slice radius, *excluding* hover pop-out room. */
    outerRadius: number
    /** Inner radius (0 for pie, > 0 for donut). */
    innerRadius: number
    /** Radians gap between adjacent slices. */
    padAngle: number
}

/** Computed layout dimensions of the chart, derived from container size and margins. */
export interface ChartDimensions {
    /** Full container width in CSS pixels. */
    width: number
    /** Full container height in CSS pixels. */
    height: number
    /** Left edge of the plot area (after left margin). */
    plotLeft: number
    /** Top edge of the plot area (after top margin). */
    plotTop: number
    /** Width of the drawable plot area. */
    plotWidth: number
    /** Height of the drawable plot area. */
    plotHeight: number
}

/** Generic scale interface that Chart uses for shared overlays and interaction. */
export interface ChartScales {
    /** Maps a label to an x pixel coordinate. For chart types where data points
     *  for the same label live at different x positions (e.g. grouped bar charts
     *  in compare-against-previous mode), pass `seriesKey` to anchor on a specific
     *  series. Falls back to the band/point center when omitted or unknown. */
    x: (label: string, seriesKey?: string) => number | undefined
    /** Maps a y value to a pixel coordinate. Uses the default (left) axis. */
    y: (value: number) => number
    /** Returns tick values for the default (left) y-axis. */
    yTicks: () => number[]
    /** Per-axis y scales keyed by axis id. Present when dual axes are active.
     *  When absent, all series use `y` / `yTicks`. */
    yAxes?: Record<string, YAxisScale>
    /** Optional horizontal data-extent at a label — bar charts populate this with the
     *  band width so {@link TooltipContext.position.width} carries it through to the
     *  tooltip overlay. Point-style charts (line, scatter) leave it unset. */
    extent?: (label: string) => number | undefined
    /** Optional cursor-aware band-slot resolver for grouped layouts. Given the hovered label
     *  and cursor (canvas pixels), returns the `{ x, width }` slot of the specific bar under the
     *  cursor, so the tooltip anchors on that bar rather than the whole group. Falls back to
     *  `x`/`extent` when absent or when it returns undefined. */
    bandSlotAtCursor?: (
        label: string,
        cursor: {
            x: number
            y: number
        }
    ) => BandSlot | undefined
    /** Chart-type-private slot. Library code MUST NOT read this — it is populated by
     *  individual chart implementations (e.g. LineChart stashes raw d3 scales here so
     *  its `drawStatic` can use them) and is opaque to the base Chart and overlays.
     *  Typed as `unknown` so d3-style types don't leak through the public surface. */
    _private?: unknown
}

export interface DragRect {
    x0: number
    x1: number
    /** Present only during a 2D (`onAreaSelect`) drag — the vertical pixel range, unordered.
     *  When absent the selection spans the full plot height. */
    y0?: number
    y1?: number
}

export interface PieSlice<Meta = unknown> {
    /** Index into the *original* (pre-exclusion) series array. */
    seriesIndex: number
    series: ResolvedSeries<Meta>
    /** Absolute slice magnitude. Negative inputs are clamped to 0 — a pie can't render them. */
    value: number
    /** value / total (0 when total is 0). */
    fraction: number
    /** Radians, 12 o'clock = 0, increasing clockwise (d3.pie convention). */
    startAngle: number
    endAngle: number
    /** Bisector angle — anchor for pop-out and on-slice labels. */
    centroidAngle: number
    color: string
}

/** Per-axis scale: a mapping function and its tick values. */
export interface YAxisScale {
    /** Maps a y value to a pixel coordinate on this axis. */
    scale: (value: number) => number
    /** Returns tick values for this axis. */
    ticks: () => number[]
    /** Visual position of this axis. */
    position: 'left' | 'right'
}

/** Band-axis slot of a single bar: left-edge coordinate (`x`) and width along the band axis.
 *  Callers derive the center as `x + width / 2` (e.g. to anchor a tooltip on the hovered bar). */
export interface BandSlot {
    x: number
    width: number
}
