// Types that 3 or more quill-charts components share.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': Series, ChartTheme, TooltipContext, PointClickData, DateRangeZoomData, SeriesType, XAxisConfig, YAxisConfig, ValueLabelsConfig, GoalLineConfig, TrendLineConfig, AxisLinesConfig, TooltipConfig, ChartLegendConfig, ChartConfig, ValueDomain, TimeInterval, YFormatterConfig, ValueLabelFormatter, LegendItem, LegendItemControls, ChartMargins, YAxis, YAxisFormat, ValueLabelContext, RadialSlicePayload, ResolvedSeries.
// Other declarations here are shapes to match, not names to import.

export interface Series<Meta = unknown> {
    /** Unique identifier used to key React elements and look up stacked data. */
    key: string
    /** Human-readable name shown in tooltips and legends. */
    label: string
    /** Numeric values for each x-axis label. Must be the same length as the labels array. */
    data: number[]
    /** CSS color string (hex, rgb) for the line and associated fill/points. Line, area, and bar
     *  series hand it to the canvas unresolved, so resolve `var(--…)` in the host first; only
     *  `Heatmap` and `ScatterChart` resolve it themselves. When omitted (or empty), the chart
     *  picks a color from `theme.colors` by series index. */
    color?: string
    /** Bar charts only: per-bar overrides of the series-level `color`/`label`/`meta`, indexed by
     *  data index. Lets one series draw bars with distinct identity (e.g. an aggregated breakdown,
     *  one bar per breakdown value) instead of paying the O(n²) cost of one series per bar. Read by
     *  bar fill, hover highlight, and the tooltip; not by track decorations (`drawBarTracks`).
     *  `hatch` fills that bar with the diagonal-hatch pattern (in the bar's resolved color) instead
     *  of a solid fill — for flagging individual not-final bars (e.g. a bucket still being
     *  ingested) without the contiguous-range constraint of `stroke.partial`. */
    bars?: {
        color?: string
        label?: string
        meta?: Meta
        hatch?: boolean
    }[]
    /** Bar charts only: per-bar ceiling (in value-axis units) of the bar's interactive extent. The
     *  region beyond the ceiling is a blank, fully inert gap — no hover, tooltip, highlight, or
     *  click (`onPointClick` passes through). On grouped charts with `bars.track`, the hatched
     *  "share of a whole" track also fills only up to `trackData[i]` instead of the whole axis; on
     *  stacked charts no track is drawn — the ceiling only bounds interactivity. Used by funnel
     *  compare to show a shorter period's volume gap as empty space rather than drop-off. Omit (or
     *  leave an entry undefined) for the default full-axis extent. */
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
        /** Whether the series' value counts toward the built-in tooltip's total row — its own row
         *  still renders. Use for series whose values don't sum meaningfully with the rest (e.g. a
         *  percentage column alongside counts). Defaults to true. */
        total?: boolean
        /** Whether the ValueLabels overlay draws a label for this series. Defaults to true. */
        valueLabel?: boolean
    }
}

/** Visual theme colours consumed by chart rendering. */
export interface ChartTheme {
    colors: string[]
    backgroundColor?: string
    axisColor?: string
    /** Stroke color for the L-shaped axis baselines and tick marks. Falls back to `axisColor`,
     *  then `gridColor` — set it to mute the lines without muting the tick label text. */
    axisLineColor?: string
    gridColor?: string
    /** Canvas dash pattern (e.g. `[3, 3]`) for interior grid lines. Solid when omitted. */
    gridDashPattern?: number[]
    crosshairColor?: string
    /** Canvas dash pattern (e.g. `[3, 3]`) for the hover crosshair. Solid when omitted. */
    crosshairDashPattern?: number[]
    tooltipBackground?: string
    tooltipColor?: string
    tooltipZIndex?: number | string
    /** Skip canvas painting while still mounting the canvas. For deterministic visual-snapshot tests. */
    skipDraw?: boolean
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
    /** Grouped layouts only: cursor is past the bar's filled extent, measured on the same rects
     *  as click routing. `undefined` for other layouts and pinned rebuilds with no cursor. */
    inTrackArea?: boolean
    /** Pixel position (relative to the chart container) for anchoring the tooltip.
     *  `width` (optional) is the horizontal data-extent centered on `x` — bar charts
     *  populate it with the band width so {@link Tooltip} can anchor at the band edge
     *  rather than the band center. Point-style charts (lines, scatter) leave it unset. */
    position: {
        x: number
        y: number
        width?: number
    }
    /** Cursor position in canvas pixels, or `null` for non-mousemove snapshots (e.g. pinned rebuild). */
    hoverPosition: {
        x: number
        y: number
    } | null
    /** Bounding rect of the canvas element, useful for portal-based tooltip positioning. */
    canvasBounds: DOMRect
    /** Whether the tooltip is pinned (clicked). When pinned, the tooltip stays visible
     *  and becomes interactive (pointer-events enabled). */
    isPinned: boolean
    /** Callback to unpin (close) a pinned tooltip. Only present when the tooltip is pinned. */
    onUnpin?: () => void
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
    crossSeriesData: {
        series: Series<Meta>
        value: number
    }[]
    /** Cursor position in pixels relative to the chart wrapper at click time, or `null`
     *  when unavailable. Same origin as `TooltipContext.hoverPosition`. */
    cursor: {
        x: number
        y: number
    } | null
    /** Grouped layouts only: `true` when the cursor was in the bar's band slot but beyond its
     *  filled value extent — i.e. the track region above (vertical) or past (horizontal) a short
     *  bar. Lets consumers route "clicked the empty remainder" differently from "clicked the bar"
     *  (e.g. funnel drop-off vs converted). `undefined` outside grouped click resolution. */
    inTrackArea?: boolean
}

export type DateRangeZoomData = LabelRange

/** How a series is rendered in a mixed-type chart. */
export type SeriesType = 'line' | 'bar' | 'area'

export interface XAxisConfig {
    label?: string
    /** Explicit tick formatter. When set, it wins over the auto date formatter. */
    tickFormatter?: (value: string, index: number) => string | null
    /** Fixed tick-label rotation in degrees, clamped to -90..90. Negative values tilt left. */
    tickLabelRotation?: number
    hide?: boolean
    /** Timezone used when interpreting date labels for the auto date formatter. */
    timezone?: string
    /** Bucket size for the auto date formatter. Inferred from `allDays` or chart labels when omitted. */
    interval?: TimeInterval
    /** Source dates for the auto date formatter. Falls back to chart labels when omitted. */
    allDays?: string[]
}

export interface YAxisConfig extends YFormatterConfig {
    /** Axis id — matches `Series.yAxisId`. Only meaningful in the array (multi-axis) form; the
     *  first entry defaults to the primary axis id (`'left'`). */
    id?: string
    /** Which side this axis renders on. Only meaningful in the array (multi-axis) form; the first
     *  entry defaults to `'left'`, subsequent entries to `'right'`. */
    position?: 'left' | 'right'
    label?: string
    scale?: 'linear' | 'log'
    /** Custom tick formatter. When set, it wins over `format`. */
    tickFormatter?: (value: number) => string
    hide?: boolean
    showGrid?: boolean
    /** Y-axis baseline behavior. The default (`undefined`/`true`) clamps a non-negative axis down to
     *  0. Set `false` to float the axis to its data range instead (zoom in on the variation). Ignored
     *  on a log scale; honored per axis in the array (multi-axis) form, except axes carrying bar
     *  series, which always draw from 0. */
    startAtZero?: boolean
    /** Pins the low end of the axis, overriding both the data-derived bound and `startAtZero`. Omit
     *  for an automatic bound. Honored per axis in the array (multi-axis) form; ignored under a
     *  percent layout, and dropped when non-positive on a log scale. Read by the line charts only:
     *  this config is shared, but bar and combo charts ignore it, since a bar encodes magnitude as
     *  length from zero. */
    min?: number
    /** Pins the high end of the axis. Omit for an automatic bound. See {@link YAxisConfig.min}. */
    max?: number
}

export interface ValueLabelsConfig {
    seriesKeys?: string[]
    /** Per-segment label text — see `ValueLabelFormatter` for the context and empty-string contract. */
    formatter?: ValueLabelFormatter
}

export interface GoalLineConfig {
    value: number
    label?: string
    displayLabel?: boolean
    color?: string
    labelPosition?: 'start' | 'end'
    displayIfCrossed?: boolean
    /** Forwarded to {@link ReferenceLineProps.showValueOnHover}; defaults to true. */
    showValueOnHover?: boolean
}

export interface TrendLineConfig {
    seriesKey: string
    kind: 'linear' | 'exponential'
    label?: string
    /** Restrict the regression fit to indices `[0, fitUpTo)`; trend is still extrapolated
     *  across the full range. Use to exclude an in-progress tail so the partial bucket
     *  doesn't drag the slope. */
    fitUpTo?: number
}

/** `showAxisLines` value — a boolean toggles both edges; `{ x, y }` toggles each independently
 *  (an omitted edge defaults to shown). */
export type AxisLinesConfig =
    | boolean
    | {
          x?: boolean
          y?: boolean
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
    /** Bar charts only. `bar` (the default) tooltips only inside a painted bar. `band` tooltips
     *  anywhere in the hovered band, so a one-pixel bar or a zero bucket still reports its value. */
    hitArea?: 'bar' | 'band'
}

/** Built-in legend config for the multi-series charts. The chart renders a {@link Legend} and,
 *  when interactive, owns the toggled-off state. A plain click isolates the clicked series — every
 *  other row is hidden (no draw, no scale contribution, no tooltip) and the axes rescale into the
 *  freed space — and clicking the isolated row again restores all; ⌘/Ctrl-click (or Shift-click)
 *  toggles one series in or out. Pass `hiddenKeys` + `onToggleSeries` to control the state
 *  yourself instead, and `onSetHiddenSeries` alongside them to keep isolating. */
export interface ChartLegendConfig {
    /** Render the legend. Default false. */
    show?: boolean
    /** Where the legend sits relative to the plot. Default 'bottom'. */
    position?: 'top' | 'bottom' | 'left' | 'right'
    /** Legend alignment along its axis. Default 'center'. */
    align?: 'start' | 'center' | 'end'
    /** Gap in px between the legend and the plot. */
    gap?: number
    /** Legend rows respond to clicks — isolate, or toggle with ⌘/Ctrl. Default true when the legend
     *  is shown; set false for a static, read-only legend. */
    interactive?: boolean
    /** Controlled hidden-series keys. Provide together with `onToggleSeries` to own the state, plus
     *  `onSetHiddenSeries` for the bulk actions — without it a controlled legend can't isolate and a
     *  plain click falls back to toggling. Omit all three for chart-managed (uncontrolled) state. */
    hiddenKeys?: string[]
    /** Initial hidden keys for the chart-managed (uncontrolled) state. Ignored when `hiddenKeys`
     *  is set (controlled). */
    defaultHiddenKeys?: string[]
    /** Called whenever a series is toggled, with its key and resulting hidden state. */
    onToggleSeries?: (key: string, hidden: boolean) => void
    /** Called with the whole next hidden set when a bulk action runs — a plain click isolating a
     *  series, or a row menu's isolate / hide-all. A controlled legend must handle this for those
     *  actions to work at all; `onToggleSeries` fires one key at a time and can't express them as a
     *  single update. Uncontrolled legends update their own state and don't need it. */
    onSetHiddenSeries?: (hiddenKeys: string[]) => void
    /** Groups legend rows that a consumer stores one visibility bit for, so the chart counts them as
     *  one series: isolating keeps the whole group visible, "only this one is visible" is judged per
     *  group, and a legend with one group has nothing to isolate. A chart comparing two periods needs
     *  this when a series' current and previous rows share one stored bit. `hiddenKeys` stays in row
     *  space either way — this only answers which rows are the same series, never where the consumer
     *  keeps the state. Defaults to the row's own key. */
    visibilityGroupKey?: (rowKey: string) => string
    /** Wrap each rendered legend row — receives the default row node, its item, and that row's
     *  {@link LegendItemControls} (visibility state plus toggle/isolate/hide-all actions), and
     *  returns the node to render. Lets consumers augment rows (e.g. a right-click context menu)
     *  while keeping the default swatch/label/toggle rendering. Return `defaultNode` to leave a row
     *  untouched. */
    renderItem?: (defaultNode: ReactNode, item: LegendItem, controls: LegendItemControls) => ReactNode
}

/** An x-axis range resolved to labels — the shared shape of the drag-selection payloads. */
export interface LabelRange {
    startLabel: string
    endLabel: string
    startIndex: number
    endIndex: number
}

/** Base configuration shared by all chart types. */
export interface ChartConfig {
    /** Y-axis scale type. 'log' clamps minimum to 1e-10 to avoid log(0). Defaults to 'linear'. */
    yScaleType?: 'linear' | 'log'
    /** Custom x-axis tick label formatter. Return null to skip a tick. Called with (label, index). */
    xTickFormatter?: (value: string, index: number) => string | null
    /** Fixed x-axis tick-label rotation in degrees, clamped to -90..90. Defaults to 0. */
    xTickLabelRotation?: number
    /** Custom y-axis tick label formatter. Overrides the built-in auto-precision formatter. */
    yTickFormatter?: (value: number) => string
    /** Hide the x-axis labels and reduce bottom margin. */
    hideXAxis?: boolean
    /** Hide the y-axis labels and reduce left margin. */
    hideYAxis?: boolean
    xAxisLabel?: string
    yAxisLabel?: string
    /** Show horizontal grid lines at y-axis tick positions. */
    showGrid?: boolean
    /** Draw only the L-shaped axis baselines (left + bottom) without interior grid lines. Ignored
     *  when `showGrid` is true, since the grid already frames the plot. */
    showAxisLines?: AxisLinesConfig
    /** Draw short tick marks on the axes next to each visible tick label. Pairs with
     *  `showAxisLines` for a clean, grid-free axis that still reads precisely. */
    showTickMarks?: boolean
    /** Line/area interpolation. `linear` (default) draws straight segments; `monotone` smooths the
     *  line with monotone-cubic curves that pass through every point without overshooting. */
    curve?: 'linear' | 'monotone'
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

/** Value-axis domain control (y for vertical/line/area charts, x for horizontal bars). Omit for the
 *  default: a data-derived range with `d3.nice()`.
 *
 *  Setting **both** ends pins the domain, skipping `d3.nice()` and overriding percent layout, which
 *  keeps independent charts visually comparable (e.g. funnel steps). Setting **one** clamps that end
 *  and leaves the other automatic.
 *
 *  A non-finite bound counts as unset, so `{ min: 0, max: Math.max(...[]) }` floors at zero instead
 *  of collapsing. An inverted pair falls back to the automatic domain rather than being swapped,
 *  because these arrive from saved queries, the API, and MCP, where a silent reinterpretation would
 *  render an axis nobody asked for. */
export interface ValueDomain {
    /** Widen the domain to cover these values (e.g. off-scale goal lines). Folded in before
     *  `d3.nice()`. Ignored once both `min` and `max` are set. */
    include?: readonly number[]
    /** Floor of the value axis, applied after `include` folding, the zero clamp and `d3.nice()`, and
     *  used verbatim so a typed bound isn't rounded away. Ignored under a percent layout, and dropped
     *  when non-positive on a log scale. */
    min?: number
    /** Ceiling of the value axis. See {@link ValueDomain.min}. */
    max?: number
}

/** Bucket size for a date-based X axis. Mirrors `IntervalType` from product code without
 * coupling hog-charts to it. */
export type TimeInterval = 'second' | 'minute' | 'hour' | 'day' | 'week' | 'month' | 'quarter' | 'year'

export interface YFormatterConfig {
    /** `percentage` expects values in `0–100`; `percentage_scaled` expects values in `0–1`. */
    format?: YAxisFormat
    prefix?: string
    suffix?: string
    decimalPlaces?: number
    minDecimalPlaces?: number
    /** Currency code (e.g. `'USD'`). Used when `format === 'currency'`. */
    currency?: string
}

/** Returning an empty string skips the label entirely. */
export type ValueLabelFormatter = (
    value: number,
    /** `-1` for stack-total labels. */
    seriesIndex: number,
    dataIndex: number,
    context: ValueLabelContext
) => string

export interface LegendItem {
    key: string
    label: string
    color: string
    /** Optional trailing text shown muted after the label — e.g. a slope chart's per-series change. */
    secondaryLabel?: string
}

/** One legend row's visibility state plus the actions that can change it, handed to
 *  {@link ChartLegendConfig.renderItem} so a consumer's row menu doesn't re-derive any of it. The
 *  actions run the same paths as clicking (`isolate`) and ⌘/Ctrl-clicking (`toggle`) the row. */
export interface LegendItemControls {
    /** This row's series is toggled off. */
    isHidden: boolean
    /** This row's group is the only visible one — i.e. it is currently isolated. */
    isOnlyVisible: boolean
    /** No row is toggled off. */
    areAllVisible: boolean
    /** Whether isolating does anything: it needs more than one visibility group, an interactive
     *  legend, and — when the legend is controlled — an `onSetHiddenSeries` to write through. When
     *  false, a plain click falls back to toggling this one series. */
    canIsolate: boolean
    /** Add or remove just this series, as a ⌘/Ctrl-click does. */
    toggle: () => void
    /** Show only this series — or show all of them when this one is already the only visible one.
     *  What a plain click does. */
    isolate: () => void
    /** Hide every series, or show all when any is hidden. */
    toggleAll: () => void
}

/** Spacing between the container edges and the plot area. */
export interface ChartMargins {
    top: number
    right: number
    bottom: number
    left: number
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
    /** Hide this axis's tick labels and margin gutter. The scale still applies to its series. */
    hide?: boolean
    /** `false` floats this axis to its data range instead of clamping a non-negative domain to 0. */
    startAtZero?: boolean
    /** Domain control for this axis. Set on secondary axes only: the primary axis takes the
     *  chart-level `valueDomain`, already merged with the goal-line stretch. See {@link ValueDomain}. */
    valueDomain?: ValueDomain
}

export type YAxisFormat =
    | 'numeric'
    | 'percentage'
    | 'percentage_scaled'
    | 'currency'
    | 'duration'
    | 'duration_ms'
    | 'duration_ns'
    | 'short'

/** Per-segment context handed to a value formatter so callers can compute labels that depend on
 *  the band (e.g. each segment's share of its band). Keeps band/stacking knowledge in the library
 *  while leaving the label text — values, percentages, units — entirely to the caller. */
export interface ValueLabelContext {
    /** Underlying value of this segment (the band total for stack-total labels). In percent layout
     *  the formatter's `value` arg is the segment's fraction (0..1); `rawValue` stays the original so
     *  callers can compute their own shares. */
    rawValue: number
    /** Finite values of every series contributing to this band's stack (non-excluded, not a fill
     *  lower-bound, not an overlay) at this dataIndex — the denominator set for share math. */
    bandValues: number[]
    /** Same as `bandValues` for the preceding dataIndex; empty at the first index. */
    previousBandValues: number[]
    /** True in normalized/percent layout, where `value` is already a fraction. */
    isPercent: boolean
}

export interface RadialSlicePayload<Meta = unknown> {
    sliceIndex: number
    series: ResolvedSeries<Meta>
    value: number
    fraction: number
}

/** Series shape after the chart has applied its color fallback from `theme.colors`.
 *  This is the type seen by overlays, draw functions, and interaction code — by the time
 *  those run, `color` is guaranteed to be set. Public consumers should write {@link Series}
 *  with color either supplied or omitted (chart picks one) and let the chart resolve it. */
export type ResolvedSeries<Meta = unknown> = Series<Meta> & {
    color: string
}
