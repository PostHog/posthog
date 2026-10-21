// Types of `FunnelChart`. Shared types it uses, declared in core.d.ts: Series, ChartTheme, TooltipContext, SeriesType, TooltipConfig, ChartLegendConfig, ChartMargins, PointClickData, LegendItem, LegendItemControls.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': FunnelChart, funnelFromCounts, FunnelChartProps, FunnelStepCount, FunnelFromCountsOptions, FunnelChartConfig, FunnelStepClickData.
// Other declarations here are shapes to match, not names to import.

/** Funnel steps as grouped vertical bars — each step a band, each variant a bar valued by its
 *  conversion from the first step, with a hatched track behind it covering the drop-off remainder.
 *  A thin wrapper over {@link BarChart}; overlays compose as children the same way. */
export declare function FunnelChart<Meta = unknown>({
    steps,
    series,
    theme,
    config,
    tooltip,
    onStepClick,
    stepFooter,
    dataAttr,
    className,
    children,
    onError,
}: FunnelChartProps<Meta>): React.ReactElement

/** Builds the `steps` + single-`series` pair for a no-breakdown funnel from raw step counts,
 *  with each step valued as its conversion from the first step (percent, 0–100). Multi-variant
 *  funnels resolve their own per-variant percentages and pass
 *  `Series[]` directly. */
export declare function funnelFromCounts(
    steps: FunnelStepCount[],
    options?: FunnelFromCountsOptions
): {
    steps: string[]
    series: Series[]
}

export interface FunnelChartProps<Meta = unknown> {
    /** Step display labels, in order. Duplicates are fine — bands are keyed by step index
     *  internally, so two steps sharing an event name keep separate slots. */
    steps: string[]
    /** One series per variant (a single series without a breakdown); `data[stepIndex]` is the
     *  conversion from the first step as a percent (0–100). The hatched track drawn behind each
     *  bar covers the remainder up to 100%. See `funnelFromCounts` for the raw-counts case. */
    series: Series<Meta>[]
    theme: ChartTheme
    config?: FunnelChartConfig
    /** Custom tooltip content. Omit for the built-in tooltip with percent formatting. */
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    /** Click on a bar (converted) or its drop-off track. Replaces `onPointClick`. */
    onStepClick?: (data: FunnelStepClickData<Meta>) => void
    /** Per-step content rendered in a row below the plot, horizontally aligned under each
     *  step's bars — for step legends richer than an axis label. Hides the built-in step labels. */
    stepFooter?: (stepIndex: number) => React.ReactNode
    dataAttr?: string
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export interface FunnelStepCount {
    label: string
    count: number
}

export interface FunnelFromCountsOptions {
    key?: string
    label?: string
    color?: string
}

export interface FunnelChartConfig {
    /** Tooltip behaviour + built-in content formatting. Defaults to `top` placement with a
     *  percent value formatter and step names in the header. */
    tooltip?: TooltipConfig
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
    animateHover?: boolean | number
    margins?: Partial<ChartMargins>
    /** Show horizontal grid lines at value-axis ticks. Defaults to true. */
    showGrid?: boolean
    /** Corner radius of the bar tops. Defaults to 10. */
    barCornerRadius?: number
    /** Hide the built-in step-name labels under the plot. Implied when `stepFooter` is set —
     *  the footer row replaces the axis labels. */
    hideStepLabels?: boolean
    /** Hide the percent value axis. */
    hideValueAxis?: boolean
    /** Truncate long step-name labels to this px width (ellipsis + hover reveal). */
    maxCategoryLabelWidth?: number
    /** Inner gap between variant bars as a fraction of the band slot. Defaults to {@link FUNNEL_BAND_PADDING}. */
    bandPadding?: number
    /** Min px hover/click extent of a non-zero bar. Defaults to {@link FUNNEL_MIN_BAR_SIZE}; 0 disables. */
    minBarSize?: number
    /** Cap (px) on the band-axis range — clusters steps at the start of the plot instead of
     *  stretching a 2–3 step funnel across the full width. */
    maxBandRange?: number
    /** Min pixel height of the chart region when `stepFooter` is set, so a tall footer can't
     *  collapse the canvas to zero height in a height-constrained parent. */
    chartMinHeight?: number
    /** Where each `stepFooter` cell sits relative to its step's bars. `start` (default) begins the
     *  cell at the bars' left edge and extends it over the gap to the right. `center` extends it
     *  over half the gap on each side, so centered footer content lines up under the bars. */
    stepFooterAlign?: 'start' | 'center'
}

export interface FunnelStepClickData<Meta = unknown> extends PointClickData<Meta> {
    /** Index into `steps` of the clicked band. Same value as `dataIndex`, named for funnel call sites. */
    stepIndex: number
    /** True when the filled (converted) portion of a bar was clicked; false for the hatched
     *  drop-off track above it. */
    converted: boolean
}
