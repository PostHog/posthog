// Types of `Sparkline`. Shared types it uses, declared in core.d.ts: Series, ChartTheme, ValueDomain, TooltipContext, SeriesType.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': Sparkline, SparklineProps.
// Other declarations here are shapes to match, not names to import.

export declare function Sparkline(props: SparklineProps): React.ReactElement

export interface SparklineProps {
    /** Single-series values. Ignored when `series` is provided. */
    data?: number[]
    /** Multi-series form with full per-series control (color, fill, stroke). Bars render stacked.
     *  When set, the single-series conveniences (`data`, `color`, `fillOpacity`,
     *  `dashedFromIndex`) are ignored — express them on the series entries instead. */
    series?: Series[]
    /** Optional x-axis labels — when omitted, indices stand in. Consumers can look up
     *  the hovered index against their own labels. */
    labels?: string[]
    theme: ChartTheme
    color?: string
    /** `line` (default) draws a gradient-filled trend line; `bar` draws stacked bars. */
    type?: 'line' | 'bar'
    height?: number
    /** Fill the parent's height (flex child) instead of using a fixed `height`. */
    fill?: boolean
    /** Peak opacity of the gradient fill under the line. Range 0–1. */
    fillOpacity?: number
    /** Dash the line from this index onward (e.g. an in-progress trailing period). Omit for a fully solid line. */
    dashedFromIndex?: number
    /** Value-axis domain control — omit for data-derived auto-scaling. Pin both ends to keep
     *  separate sparklines comparable (e.g. a column of per-provider rates all read against 0–100). */
    valueDomain?: ValueDomain
    /** Fires the hovered index, or -1 when not hovering. */
    onHoverIndexChange?: (index: number) => void
    /** Tooltip content renderer. Sparkline tooltips are off by default; supplying this enables them. */
    tooltip?: (ctx: TooltipContext) => React.ReactNode
    className?: string
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}
