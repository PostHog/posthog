// Types of `Chart`. Shared types it uses, declared in core.d.ts: ChartConfig, Series, ChartTheme, TooltipContext, PointClickData, DateRangeZoomData, AxisLinesConfig, TooltipConfig, ChartMargins, YAxis, SeriesType, ResolvedSeries, LabelRange, ValueDomain.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': Chart, applyChartDefaults, ChartProps, CreateScalesFn, ChartDrawArgs, AreaSelectData, ChartScales, ResolveValueFn, ChartDimensions, DragRect, YAxisScale.
// Other declarations here are shapes to match, not names to import.

export declare function Chart<Meta = unknown>({
    series,
    labels,
    config,
    theme,
    createScales: createScalesFn,
    drawStatic,
    drawHover,
    tooltip: renderTooltipProp,
    onPointClick,
    isPointClickable,
    onDateRangeZoom,
    onAreaSelect,
    className,
    dataAttr,
    children,
    resolveValue,
    resolvePositionValue,
    resolveBottomValue,
    labelToCoord,
    valueRangeSeries,
    wrapClickData,
    resolveHoverIndex,
}: ChartProps<Meta>): React.ReactElement

/** Layers `DEFAULT_CHART_CONFIG` under a chart's config: any field the consumer sets wins, an
 *  unset or explicitly `undefined` field falls back to the default, and `tooltip` merges key by key
 *  — dropping `undefined` at both levels — so setting one tooltip field never drops
 *  `placement: 'cursor'`. */
export declare function applyChartDefaults<T extends ChartConfig>(config?: T): T

export interface ChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: ChartConfig
    theme: ChartTheme
    createScales: CreateScalesFn
    /** Static layer — grid, lines, areas, points. Redrawn only when chart inputs change. */
    drawStatic: (args: ChartDrawArgs) => void
    /** Hover overlay — highlight rings only. Return `false` if nothing was drawn (the
     *  hover-fade timer pauses while invisible). */
    drawHover: (args: ChartDrawArgs) => DrawHoverResult
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    /** Limits `onPointClick` and the pointer cursor to the points it returns true for. */
    isPointClickable?: (dataIndex: number) => boolean
    /** Enables x-axis drag-to-zoom. Fired with the label range the user dragged across.
     *  x-axis only — has no effect on charts with a vertical (`interactionAxis: 'y'`) interaction. */
    onDateRangeZoom?: (data: DateRangeZoomData) => void
    /** Enables a 2D brush: the drag tracks both axes, the selection rect clamps to the dragged
     *  vertical range, and the completed gesture reports the x label range plus the y pixel
     *  span, with the committed `scales` so chart-type adapters can map pixels onto their own
     *  bands. Takes precedence over `onDateRangeZoom`. Chart-type adapters provide this and
     *  expose a domain-shaped callback (e.g. Heatmap's `onBrush`); consumers do not. */
    onAreaSelect?: (data: AreaSelectData, scales: ChartScales) => void
    className?: string
    dataAttr?: string
    children?: React.ReactNode
    /** Resolves the y-value to *display* for a series at a given index. Defaults to
     *  series.data[index]. Identity is read live for tooltip values, but the pinned-tooltip
     *  rebuild only refires when `series`, `labels`, or `scales` change. Callers that
     *  derive values from data not reflected in those (e.g. an external "%" toggle)
     *  should ensure that toggle also updates `series` or the chart's scales — otherwise
     *  a held pin will keep showing values from the previous resolver. */
    resolveValue?: ResolveValueFn
    /** Value used to *anchor* the tooltip and value-label overlays per series. Defaults to
     *  `resolveValue`. Stacked charts pass the stacked-top resolver here so overlays land at the
     *  visual top of each segment, while each tooltip row still shows that series's own value
     *  via `resolveValue`. */
    resolvePositionValue?: ResolveValueFn
    /** Resolves the stacked bottom value per series — used to compute segment midpoints for
     *  tooltip closest-series detection. Only bar charts provide this. */
    resolveBottomValue?: ResolveValueFn
    /** Required for horizontal orientation — maps labels to the coordinate on the categorical
     *  axis (y in horizontal mode). Should be referentially stable; non-stable identities
     *  invalidate the interaction memo on every render. */
    labelToCoord?: (label: string) => number | undefined
    /** Override the series fed into value-axis tick sizing (`useChartMargins`). Use when the
     *  visible series's `data[i]` doesn't span the y-domain — e.g. BoxPlot passes synthetic
     *  whisker min/max samples so the y-tick column fits the real value range, not just the
     *  medians it draws on `series.data`. */
    valueRangeSeries?: Series[]
    /** Chart-type seam: rewrite the click payload (e.g. resolve the stacked segment under the
     *  cursor) before it reaches `onPointClick`, using the committed `scales` from this render.
     *  Chart-type adapters provide this; consumers do not. */
    wrapClickData?: (data: PointClickData<Meta>, scales: ChartScales) => PointClickData<Meta>
    /** Chart-type seam: given the nearest band index and cursor, return the effective hover index — or
     *  -1 to make the position a dead zone (no tooltip, pointer cursor, highlight, or click). Chart-type
     *  adapters provide this; BarChart uses it for a capped track's blank volume gap. */
    resolveHoverIndex?: (
        index: number,
        cursor: {
            x: number
            y: number
        },
        scales: ChartScales
    ) => number
}

/** Factory function that chart types provide to create their scales from dimensions and data. */
export type CreateScalesFn = (series: ResolvedSeries[], labels: string[], dimensions: ChartDimensions) => ChartScales

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

/** Payload of a completed 2D brush ({@link ChartProps.onAreaSelect}). The x axis resolves to
 *  labels like `onDateRangeZoom`; the y axis stays in canvas pixels — the core is label-generic
 *  and has no y-band concept, so chart-type adapters map the pixel range onto their own scales
 *  (e.g. the Heatmap converts it to row indices). The raw x pixels come along too, for chart types
 *  whose x axis is continuous rather than a band (e.g. ScatterChart inverts them back to data
 *  values), where the label range would round the selection to whichever points sit near the drag
 *  edges. */
export interface AreaSelectData extends LabelRange {
    /** Left edge of the dragged range in canvas pixels (always <= xPixel1). */
    xPixel0: number
    /** Right edge of the dragged range in canvas pixels. */
    xPixel1: number
    /** Top of the dragged range in canvas pixels (always <= yPixel1). */
    yPixel0: number
    /** Bottom of the dragged range in canvas pixels. */
    yPixel1: number
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

/** Resolves the y-value for a series at a given data index. Used by interaction/tooltip layer. */
export type ResolveValueFn = (series: Series, dataIndex: number) => number

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

export interface DragRect {
    x0: number
    x1: number
    /** Present only during a 2D (`onAreaSelect`) drag — the vertical pixel range, unordered.
     *  When absent the selection spans the full plot height. */
    y0?: number
    y1?: number
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
