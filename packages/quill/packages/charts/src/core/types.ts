import type { ReactNode } from 'react'

import type { LegendItem } from '../components/Legend/Legend'

/** Visual theme colours consumed by chart rendering. */
export interface ChartTheme {
    colors: string[]
    backgroundColor?: string
    axisColor?: string
    gridColor?: string
    crosshairColor?: string
    tooltipBackground?: string
    tooltipColor?: string
    tooltipZIndex?: number | string
    /** Skip canvas painting while still mounting the canvas. For deterministic visual-snapshot tests. */
    skipDraw?: boolean
}

/** Default axis id used when a series doesn't specify one. */
export const DEFAULT_Y_AXIS_ID = 'left'

/** Series shape after the chart has applied its color fallback from `theme.colors`.
 *  This is the type seen by overlays, draw functions, and interaction code — by the time
 *  those run, `color` is guaranteed to be set. Public consumers should write {@link Series}
 *  with color either supplied or omitted (chart picks one) and let the chart resolve it. */
export type ResolvedSeries<Meta = unknown> = Series<Meta> & { color: string }

/** How a series is rendered in a mixed-type chart. */
export type SeriesType = 'line' | 'bar' | 'area'

/** Series type assumed when a `Series` sets no explicit `type`. */
export const DEFAULT_SERIES_TYPE: SeriesType = 'line'

export interface Series<Meta = unknown> {
    /** Unique identifier used to key React elements and look up stacked data. */
    key: string
    /** Human-readable name shown in tooltips and legends. */
    label: string
    /** Numeric values for each x-axis label. Must be the same length as the labels array. */
    data: number[]
    /** CSS color string (hex, rgb, var(--…), etc.) for the line and associated fill/points.
     *  When omitted (or empty), the chart picks a color from `theme.colors` by series index. */
    color?: string
    /** Bar charts only: per-bar overrides of the series-level `color`/`label`/`meta`, indexed by
     *  data index. Lets one series draw bars with distinct identity (e.g. an aggregated breakdown,
     *  one bar per breakdown value) instead of paying the O(n²) cost of one series per bar. Read by
     *  bar fill, hover highlight, and the tooltip; not by track decorations (`drawBarTracks`). */
    bars?: { color?: string; label?: string; meta?: Meta }[]
    /** Grouped bar charts with `bars.track` only: per-bar ceiling (in value-axis units) for the
     *  "share of a whole" track. The hatched track fills only up to `trackData[i]` instead of the
     *  whole axis, and the region beyond it is a blank, non-interactive gap — no track highlight, no
     *  click (`onPointClick` passes through). Used by funnel compare to show a shorter period's
     *  volume gap as empty space rather than drop-off. Omit (or leave an entry undefined) for the
     *  default full-axis track. */
    trackData?: number[]
    /** Which y-axis this series is scaled against. Defaults to {@link DEFAULT_Y_AXIS_ID}. */
    yAxisId?: string
    /** Mixed-type charts ({@link ComboChart}) read this to draw the series as a bar, line, or
     *  area. Falls back to the chart's `defaultSeriesType` when omitted. Ignored by single-type
     *  charts. */
    type?: SeriesType
    /** Arbitrary consumer data attached to this series. Flows through to TooltipContext
     *  so custom tooltip components can access domain-specific information (e.g. breakdown
     *  values, comparison labels, anomaly scores) without the library needing to know about them.
     *  Defaults to `unknown` so the library is meta-agnostic internally; adapters narrow it
     *  via `Series<MyMeta>` to get typed reads in their tooltip/click handlers. */
    meta?: Meta
    /** Point markers configuration. Omit for no dots. */
    points?: {
        /** Radius in CSS pixels. */
        radius: number
    }
    /** Line stroke configuration. */
    stroke?: {
        /** Canvas line dash pattern, e.g. [10, 10] for evenly dashed. Omit for solid. */
        pattern?: number[]
        /** A range of indices that should be drawn with a different (typically dashed) pattern. */
        partial?: {
            /** Index from which the partial pattern starts (inclusive). Clamped to [0, data.length-1]. */
            fromIndex?: number
            /** Index up to which the partial pattern applies (inclusive). Clamped to [0, data.length-1]. */
            toIndex?: number
            /** Split the *final* segment at this fraction (0–1) of its length and dash only the part
             *  beyond it — everything before stays solid. Lets a two-point line dash just its second
             *  half without a phantom interior point. Takes precedence over `fromIndex`/`toIndex`. */
            fromFraction?: number
            /** Dash pattern for the partial range. Defaults to [10, 10]. */
            pattern?: number[]
        }
    }
    /** Area fill configuration. Presence implies the area between the line and baseline is filled. */
    fill?: {
        /** Opacity of the area fill. Range 0–1. Defaults to 0.5. */
        opacity?: number
        /** Bottom-edge data for fill-between rendering (e.g. confidence interval lower bound).
         *  When set, the area is drawn between `data` (top) and this (bottom) instead of
         *  filling down to the x-axis baseline. */
        lowerData?: number[]
        /** Fade the fill vertically from the series color at the top of the plot to transparent
         *  at the baseline. Ignored when the area has a bottom edge — stacking or `lowerData`
         *  (those need a solid fill). With a dashed `stroke.partial` the gradient is kept and only
         *  the stroke dashes; non-gradient area fills instead hatch the dashed range. */
        gradient?: boolean
    }
    /** Auxiliary overlay derived from primary data — trend lines and moving averages.
     *  Excluded from stack computation and from the y-axis baseline calculation, so a
     *  trendline projection won't drag the axis below 0 when the underlying data is
     *  non-negative. (CI bands are not overlays — they represent real data uncertainty
     *  whose range should still influence the axis.) */
    overlay?: boolean
    /** Per-location visibility flags — control where this series appears. */
    visibility?: {
        /** Fully exclude the series — no rendering, no scale contribution, no tooltip, no hit-testing. */
        excluded?: boolean
        /** Whether the series appears in the tooltip's seriesData. Defaults to true. */
        tooltip?: boolean
        /** Whether the ValueLabels overlay draws a label for this series. Defaults to true. */
        valueLabel?: boolean
    }
}

/** Data passed to the `onPointClick` callback when a user clicks a data point. */
export interface PointClickData<Meta = unknown> {
    /** Index of the primary series within the original series array. */
    seriesIndex: number
    /** Index along the x-axis (into the labels array) that was clicked. */
    dataIndex: number
    /** Primary series at the clicked column. */
    series: Series<Meta>
    /** The y-value of the primary series at the clicked column. */
    value: number
    /** The x-axis label at the clicked point. */
    label: string
    /** Values from all visible series at this x-axis index, for cross-series comparisons. */
    crossSeriesData: { series: Series<Meta>; value: number }[]
    /** Cursor position in pixels relative to the chart wrapper at click time, or `null`
     *  when unavailable. Same origin as `TooltipContext.hoverPosition`. */
    cursor: { x: number; y: number } | null
    /** Grouped layouts only: `true` when the cursor was in the bar's band slot but beyond its
     *  filled value extent — i.e. the track region above (vertical) or past (horizontal) a short
     *  bar. Lets consumers route "clicked the empty remainder" differently from "clicked the bar"
     *  (e.g. funnel drop-off vs converted). `undefined` outside grouped click resolution. */
    inTrackArea?: boolean
}

/** Context object passed to the `renderTooltip` render prop and tooltip event callbacks. */
export interface TooltipContext<Meta = unknown> {
    /** Index along the x-axis that the tooltip represents. */
    dataIndex: number
    /** The x-axis label at this index. */
    label: string
    /** One entry per visible series with its value and color at this index. `fraction` is set
     *  for radial charts (share of total) so renderers don't need to look the slice back up. */
    seriesData: {
        series: Series<Meta>
        value: number
        color: string
        fraction?: number
        /** Canvas y-pixel of the value-axis anchor for this series (top of bar segment, or dot for lines). */
        yPixel?: number
        /** Canvas y-pixel of the bottom of this series's bar segment. When both yPixel and
         *  yPixelBottom are present, hover detection uses range containment rather than
         *  distance-to-midpoint, giving correct results regardless of segment size differences. */
        yPixelBottom?: number
    }[]
    /** Key of the series whose bar/segment is under the cursor. Set only by BarChart's
     *  cursor narrowing (stacked: the visible segment containing the cursor; grouped: the
     *  band-slot hit) — `undefined` for other chart types and for pinned rebuilds with no
     *  cursor. May reference a series hidden from `seriesData` via `visibility.tooltip:
     *  false` (e.g. a drop-off filler segment), so callers must not assume a matching
     *  `seriesData` entry exists. */
    hoveredSeriesKey?: string
    /** Pixel position (relative to the chart container) for anchoring the tooltip.
     *  `width` (optional) is the horizontal data-extent centered on `x` — bar charts
     *  populate it with the band width so {@link Tooltip} can anchor at the band edge
     *  rather than the band center. Point-style charts (lines, scatter) leave it unset. */
    position: { x: number; y: number; width?: number }
    /** Cursor position in canvas pixels, or `null` for non-mousemove snapshots (e.g. pinned rebuild). */
    hoverPosition: { x: number; y: number } | null
    /** Bounding rect of the canvas element, useful for portal-based tooltip positioning. */
    canvasBounds: DOMRect
    /** Whether the tooltip is pinned (clicked). When pinned, the tooltip stays visible
     *  and becomes interactive (pointer-events enabled). */
    isPinned: boolean
    /** Callback to unpin (close) a pinned tooltip. Only present when the tooltip is pinned. */
    onUnpin?: () => void
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

/** Spacing between the container edges and the plot area. */
export interface ChartMargins {
    top: number
    right: number
    bottom: number
    left: number
}

/** Base configuration shared by all chart types. */
export interface ChartConfig {
    // — Scale —

    /** Y-axis scale type. 'log' clamps minimum to 1e-10 to avoid log(0). Defaults to 'linear'. */
    yScaleType?: 'linear' | 'log'
    // — Axis formatting —

    /** Custom x-axis tick label formatter. Return null to skip a tick. Called with (label, index). */
    xTickFormatter?: (value: string, index: number) => string | null
    /** Custom y-axis tick label formatter. Overrides the built-in auto-precision formatter. */
    yTickFormatter?: (value: number) => string
    /** Hide the x-axis labels and reduce bottom margin. */
    hideXAxis?: boolean
    /** Hide the y-axis labels and reduce left margin. */
    hideYAxis?: boolean
    xAxisLabel?: string
    yAxisLabel?: string

    // — Overlays —

    /** Show horizontal grid lines at y-axis tick positions. */
    showGrid?: boolean
    /** Draw only the L-shaped axis baselines (left + bottom) without interior grid lines. Ignored
     *  when `showGrid` is true, since the grid already frames the plot. */
    showAxisLines?: boolean
    /** Tooltip behaviour. Defaults to enabled with no pinning and `follow-data` placement. */
    tooltip?: TooltipConfig
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** `vertical` (default): categories on x, values on y. `horizontal`: swapped. */
    axisOrientation?: 'vertical' | 'horizontal'
    /** True for BarChart `barLayout: 'percent'` / LineChart `percentStackView`. Surfaced
     *  on layout context so overlays can default to a percent formatter. */
    isPercent?: boolean
    /** Fade-in the hover overlay when the hovered point changes. `true` = ~150ms. */
    animateHover?: boolean | number
    /** Per-side overrides applied on top of the computed chart margins. Useful for sparklines
     *  that want the plot area flush with the canvas edges (e.g. `{ left: 0, right: 0, top: 0, bottom: 0 }`).
     *  Should be referentially stable — pass a module-level constant rather than an inline object. */
    margins?: Partial<ChartMargins>
    /** Max pixel width for category (band) tick labels before they're truncated with an ellipsis,
     *  with the full value revealed on hover. Also clamps the axis margin to this width so a long
     *  label can't push the plot off screen. Omit (default) to render labels untruncated. */
    maxCategoryLabelWidth?: number
    /** Per-axis config for multi-axis (dual y-axis) charts — one entry per distinct
     *  {@link Series.yAxisId}. When set, each axis formats ticks, labels, and scales independently;
     *  the scalar `yScaleType`/`yTickFormatter`/`yAxisLabel` then describe the primary (left) axis.
     *  Omit for single-axis charts. */
    yAxes?: YAxis[]
}

/** A resolved y-axis for a multi-axis (dual y-axis) chart. One entry per distinct
 *  {@link Series.yAxisId}; series resolve to their axis by id. Drives each axis's scale type,
 *  tick formatting, side, and label independently. */
export interface YAxis {
    /** Axis id — matches {@link Series.yAxisId}. The default-axis id is {@link DEFAULT_Y_AXIS_ID}. */
    id: string
    /** Which side this axis renders on. */
    position: 'left' | 'right'
    /** Scale type for this axis. Defaults to 'linear'. */
    scaleType?: 'linear' | 'log'
    /** Resolved tick formatter for this axis. When omitted, ticks auto-format against their values. */
    tickFormatter?: (value: number) => string
    /** Axis title. */
    label?: string
}

/** Built-in legend config for the multi-series charts. The chart renders a {@link Legend} and,
 *  when interactive, owns the toggled-off state — clicking a row hides that series (no draw, no
 *  scale contribution, no tooltip) and the axes rescale, matching the classic insight legend.
 *  Pass `hiddenKeys` + `onToggleSeries` to control the state yourself instead. */
export interface ChartLegendConfig {
    /** Render the legend. Default false. */
    show?: boolean
    /** Where the legend sits relative to the plot. Default 'bottom'. */
    position?: 'top' | 'bottom' | 'left' | 'right'
    /** Legend alignment along its axis. Default 'center'. */
    align?: 'start' | 'center' | 'end'
    /** Gap in px between the legend and the plot. */
    gap?: number
    /** Clicking a legend item hides/shows its series. Default true when the legend is shown;
     *  set false for a static, read-only legend. */
    interactive?: boolean
    /** Controlled hidden-series keys. Provide together with `onToggleSeries` to own the state;
     *  omit for chart-managed (uncontrolled) toggling. */
    hiddenKeys?: string[]
    /** Initial hidden keys for the chart-managed (uncontrolled) state. Ignored when `hiddenKeys`
     *  is set (controlled). */
    defaultHiddenKeys?: string[]
    /** Called whenever a series is toggled, with its key and resulting hidden state. */
    onToggleSeries?: (key: string, hidden: boolean) => void
    /** Wrap each rendered legend row — receives the default row node and its item, returns the
     *  node to render. Lets consumers augment rows (e.g. a right-click context menu) while keeping
     *  the default swatch/label/toggle rendering. Return `defaultNode` to leave a row untouched. */
    renderItem?: (defaultNode: ReactNode, item: LegendItem) => ReactNode
}

export interface TooltipConfig {
    /** Show a tooltip on hover. Defaults to true. */
    enabled?: boolean
    /** When true, clicking a data point with multiple series pins the tooltip in place. */
    pinnable?: boolean
    /** When a pinnable tooltip covers multiple series, resolve the series nearest the cursor and
     *  fire `onPointClick` for it directly instead of pinning — skips the pin-then-click-a-row
     *  step. Opt-in per chart; default false keeps the pin-first flow for ambiguous multi-series
     *  charts (e.g. overlapping trend lines) where a wrong guess is costly. */
    resolveClickToNearestSeries?: boolean
    /** Where the tooltip anchors. `follow-data` (default) tracks the highest data point at the
     *  hovered x; `top` fixes the tooltip to the top of the chart so it doesn't jump vertically
     *  as the cursor moves between data points; `cursor` tracks the mouse, so the tooltip sits
     *  beside the cursor and the hovered bar (chart.js-style) rather than at a fixed anchor. */
    placement?: 'follow-data' | 'top' | 'cursor'
    // Built-in DefaultTooltip content, applied only when no `tooltip` render prop is given. See
    // DefaultTooltipProps for semantics — these mirror it.
    /** Second arg is the row's `seriesData` entry, for per-series formatting. */
    valueFormatter?: (value: number, entry: TooltipContext['seriesData'][number]) => string
    /** Transforms the raw x-axis label before showing it in the tooltip header — use to convert
     *  ISO datetime strings to human-readable dates. */
    labelFormatter?: (label: string) => string
    showTotal?: boolean
    totalLabel?: string
    totalFormatter?: (value: number) => string
    /** Sort series rows by value descending so the highest value appears at the top. */
    sortedByValue?: boolean
}

/** How the value axis domain is determined (y for vertical/line/area charts, x for horizontal
 *  bars). The two modes are mutually exclusive by construction — pick one. Omit the option
 *  entirely for the default: a data-derived range with `d3.nice()`. */
export type ValueDomain =
    /** Pin both ends — skips the data-derived range and `d3.nice()` so independent charts that
     *  share this domain stay visually comparable (e.g. funnel steps). Takes precedence over
     *  `barLayout: 'percent'` / `percentStackView`. */
    | readonly [number, number]
    /** Keep data-derived auto-scaling, but stretch the domain to always cover these values
     *  (e.g. goal-line targets that sit outside the data). Folded into the range before
     *  `d3.nice()`. */
    | { include: readonly number[] }

/** Bar appearance + band-layout details. Grouped under {@link BarChartConfig.bars} to keep the
 *  config flat at the top level. `barLayout` stays top-level as the primary discriminator. */
export type BarFillStyle = 'flat' | 'gradient' | 'gloss'

export interface BarsConfig {
    /** Corner radius in px for the rounded end(s) of a bar. Stacked bars only round the topmost
     *  segment. Defaults to 0 (square). */
    cornerRadius?: number
    /** Draw a faint hatched track behind each bar, spanning the full plot height — for
     *  funnel-style charts where every bar is a share of a whole. Only honored when
     *  `barLayout: 'grouped'`; ignored for stacked/percent (the "share of a whole"
     *  semantics don't apply when bars share a band). Defaults to `false`. `true` also
     *  highlights the track region on hover; pass `{ hover: false }` to draw the track
     *  but leave it inert (no highlight when the cursor is over the empty remainder). */
    track?: boolean | { hover?: boolean }
    /** Drop shadow under each bar so it reads as layered over a `track`. */
    shadow?: boolean | { color: string; blur: number; offsetX?: number; offsetY?: number }
    /** Bar fill treatment. `flat` (default) is a solid color. `gradient` is a smooth diagonal
     *  light→dark sheen. `gloss` is a curved radial highlight for a glassy look. */
    fillStyle?: BarFillStyle
    /** Stacked layout only — use d3.stackOffsetDiverging so negative values stack below the zero
     *  baseline (positives above). Default `false` clamps negatives to 0. */
    divergingStack?: boolean
    /** Cap (px) on the band-axis range. Clusters bars at the start of the plot while gridlines
     *  still span the full width — useful for few-category funnel-style charts. */
    maxBandRange?: number
    /** Inner gap between bars as a fraction of the band slot (0–1). Outer padding is half this
     *  value, so `step = range / N`. Defaults to `DEFAULT_BAND_PADDING` in `scales.ts`. */
    bandPadding?: number
    /** Horizontal bar charts only — minimum px per row. When many rows would otherwise crush into
     *  an unreadable strip, the chart expands its container height so each row has at least this
     *  much vertical space (label height + breathing room). Defaults to `24`. Pass `0` to opt out. */
    minBandSize?: number
    /** Horizontal bar charts only — fit the chart to the height it's given instead of expanding the
     *  container (the {@link minBandSize} default behavior). Rows that don't fit at `minBandSize` are
     *  dropped, keeping the leading (value-sorted) rows, so bands never crush below `minBandSize` and
     *  the container never grows or scrolls. Use inside fixed-height tiles such as dashboard cards. */
    fitToHeight?: boolean
    /** Value-axis domain control — omit for data-derived auto-scaling. See {@link ValueDomain}. */
    valueDomain?: ValueDomain
    /** Px of headroom reserved past the bars at the value-axis data end(s), so overlays have room
     *  beyond the bar tip — e.g. a `ValueLabels` overlay can float beside/above each bar instead of
     *  being flipped onto it (an on-bar label looks like the bar grows when it lifts on hover). The
     *  axis range converts px → value units, so the gap stays visually constant. Defaults to 0. */
    valuePadding?: number
    /** Stacked layouts only — round both *outer* ends of the whole stack so it reads as one pill,
     *  rather than only the topmost segment's cap. Implemented by clipping the bar layer to a
     *  rounded rect spanning each band's full extent and drawing the segments square, so the outer
     *  corners round at the full `cornerRadius` even when the edge segment is a thin sliver (e.g.
     *  the last breakdown of a near-100% funnel step) — which per-segment rounding can't, as it
     *  clamps the radius to the sliver's half-width. Defaults to `false`. */
    roundStackEnds?: boolean
}

export interface BarChartConfig extends ChartConfig {
    /** Defaults to `stacked`. */
    barLayout?: 'stacked' | 'grouped' | 'percent'
    /** Bar appearance + band-layout details (corner rounding, track, shadow, padding…). */
    bars?: BarsConfig
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
}

export interface LineChartConfig extends ChartConfig {
    percentStackView?: boolean
    /** Value-axis domain control — omit for data-derived auto-scaling. See {@link ValueDomain}. */
    valueDomain?: ValueDomain
    /** Float the value axis to its data range instead of clamping the baseline to 0 (a y-axis "start
     *  at zero = off"). Applied to the primary axis only; ignored on a log scale. Defaults to false. */
    floatBaseline?: boolean
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
}

/** Config for {@link ComboChart}, which draws bar, line, and area series together. `axisOrientation`
 *  is omitted on purpose — bars require a band x-axis, so combo charts are vertical-only. */
export interface ComboChartConfig extends Omit<ChartConfig, 'axisOrientation'> {
    /** Type used for series that don't set {@link Series.type}. Defaults to `'line'`. */
    defaultSeriesType?: SeriesType
    /** Layout applied to *bar* series only — lines and areas never stack or group. Defaults to
     *  `'stacked'`. `'percent'` stacks bars to 100%; line/area series still plot at raw values. */
    barLayout?: 'stacked' | 'grouped' | 'percent'
    /** Corner radius for the cap of bar segments. Stacked bars only round the topmost segment. */
    barCornerRadius?: number
    /** Value-axis domain control for the primary axis — omit for data-derived auto-scaling. Used
     *  to keep off-scale goal lines on-plot (`{ include }`). See {@link ValueDomain}. */
    valueDomain?: ValueDomain
}

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
    hoverPosition: { x: number; y: number } | null
    /** Chart theme colors. */
    theme: ChartTheme
    /** Hover-fade progress (0..1). Apply as `ctx.globalAlpha` around highlight rendering. */
    hoverProgress: number
    /** Restart the hover-fade at progress 0; returns the new value to use this frame.
     *  Call when the chart type detects a visible-state change at the same hoverIndex. */
    resetHoverFade: () => number
    /** Live pixel range of an in-progress drag-to-zoom selection, x-axis only. Null when
     *  no drag is active. Only the hover overlay reads this — the static layer ignores it. */
    dragRect?: DragRect | null
}

// x0/x1 are canvas pixels, not necessarily ordered.
export interface DragRect {
    x0: number
    x1: number
}

export interface DateRangeZoomData {
    startLabel: string
    endLabel: string
    startIndex: number
    endIndex: number
}

/** `true` = drew a visible highlight; `false` = nothing visible (freeze the fade timer). */
export type DrawHoverResult = boolean

/** Resolves the y-value for a series at a given data index. Used by interaction/tooltip layer. */
export type ResolveValueFn = (series: Series, dataIndex: number) => number

export const defaultResolveValue: ResolveValueFn = (series, dataIndex) => {
    const v = series.data[dataIndex]
    return typeof v === 'number' && Number.isFinite(v) ? v : 0
}

/** Factory function that chart types provide to create their scales from dimensions and data. */
export type CreateScalesFn = (series: ResolvedSeries[], labels: string[], dimensions: ChartDimensions) => ChartScales

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

/** A laid-out box-and-whisker for a single (series, x) slot — pre-computed pixel coordinates so
 *  the draw primitives don't touch scales. Same shape contract as a bar's `BarRect`. */
export interface BoxRect {
    x: number
    width: number
    top: number
    bottom: number
    medianY: number
    mean: { x: number; y: number }
    whiskerTop: number
    whiskerBottom: number
    dataIndex: number
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
    bandSlotAtCursor?: (label: string, cursor: { x: number; y: number }) => BandSlot | undefined
    /** Chart-type-private slot. Library code MUST NOT read this — it is populated by
     *  individual chart implementations (e.g. LineChart stashes raw d3 scales here so
     *  its `drawStatic` can use them) and is opaque to the base Chart and overlays.
     *  Typed as `unknown` so d3-style types don't leak through the public surface. */
    _private?: unknown
}
