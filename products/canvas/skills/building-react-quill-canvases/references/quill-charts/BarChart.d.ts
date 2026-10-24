// Types of `BarChart`. Shared types it uses, declared in core.d.ts: Series, ChartTheme, TooltipContext, PointClickData, DateRangeZoomData, SeriesType, ChartConfig, ChartLegendConfig, LabelRange, AxisLinesConfig, TooltipConfig, ChartMargins, YAxis, ValueDomain, LegendItem, LegendItemControls.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': BarChart, BarChartProps, BarChartConfig, BarsConfig.
// Other declarations here are shapes to match, not names to import.

export declare function BarChart<Meta = unknown>({ onError, ...rest }: BarChartProps<Meta>): React.ReactElement

export interface BarChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: BarChartConfig
    theme: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    /** See `ChartProps.isPointClickable`. */
    isPointClickable?: (dataIndex: number) => boolean
    /** Enables x-axis drag-to-zoom. Vertical bars only — horizontal bars interact along y,
     *  where the gesture is disabled by the core. See `ChartProps.onDateRangeZoom`. */
    onDateRangeZoom?: (data: DateRangeZoomData) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export interface BarChartConfig extends ChartConfig {
    /** Defaults to `stacked`. */
    barLayout?: 'stacked' | 'grouped' | 'percent'
    /** Bar appearance + band-layout details (track, shadow, padding, fill style…). */
    bars?: BarsConfig
    /** Corner radius in px for the rounded end(s) of a bar. Stacked bars only round the topmost
     *  segment (or the whole stack with {@link BarsConfig.roundStackEnds}). Defaults to 0 (square).
     *  Same top-level key as the time-series/combo configs, so one config shape rounds every bar
     *  chart and shared config defaults can target them all. */
    barCornerRadius?: number
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
}

export interface BarsConfig {
    /** Draw a faint hatched track behind each bar, spanning the full plot height — for
     *  funnel-style charts where every bar is a share of a whole. Only honored when
     *  `barLayout: 'grouped'`; ignored for stacked/percent (the "share of a whole"
     *  semantics don't apply when bars share a band). Defaults to `false`. `true` also
     *  highlights the track region on hover; pass `{ hover: false }` to draw the track
     *  but leave it inert (no highlight when the cursor is over the empty remainder).
     *  `'solid'` draws one neutral track per band instead, in `theme.gridColor`, behind every bar
     *  in the band. It works on every layout, ignores `trackData`, and has no hover highlight. */
    track?:
        | boolean
        | 'solid'
        | {
              hover?: boolean
          }
    /** Drop shadow under each bar so it reads as layered over a `track`. */
    shadow?:
        | boolean
        | {
              color: string
              blur: number
              offsetX?: number
              offsetY?: number
          }
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
    /** Floor (px) on a bar's thickness along the value axis, so a present-but-tiny value stays
     *  visible instead of collapsing to a sub-pixel sliver — e.g. a single error in a volume bucket
     *  whose neighbours are in the thousands. Zero-valued bars are never floored: the point is to
     *  keep small data readable, not to draw a bar where there is no data. On a stacked chart only
     *  the outermost segment is floored: flooring an interior one would oversize a rect that the
     *  segment above immediately overpaints, while still capturing the hover and clicks meant for
     *  that segment. So a multi-series (breakdown) stack floors only its top segment — this is aimed
     *  at single-series volume charts and grouped bars. Defaults to 0 (exact heights). */
    minBarSize?: number
    /** `hover` floors only the hover highlight and hit-testing, so the resting bar keeps its true
     *  size (funnel charts). `always` (default) floors the static layer too. */
    minBarSizeScope?: 'always' | 'hover'
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
     *  corners round at the full `barCornerRadius` even when the edge segment is a thin sliver (e.g.
     *  the last breakdown of a near-100% funnel step) — which per-segment rounding can't, as it
     *  clamps the radius to the sliver's half-width. Defaults to `false`. */
    roundStackEnds?: boolean
}

/** Bar appearance + band-layout details. Grouped under {@link BarChartConfig.bars} to keep the
 *  config flat at the top level. `barLayout` stays top-level as the primary discriminator. */
export type BarFillStyle = 'flat' | 'gradient' | 'gloss'
