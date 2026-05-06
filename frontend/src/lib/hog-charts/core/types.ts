import type { ChartTheme } from 'lib/charts/types'
export type { ChartTheme }

/** Default axis id used when a series doesn't specify one. */
export const DEFAULT_Y_AXIS_ID = 'left'

/** Series shape after the chart has applied its color fallback from `theme.colors`.
 *  This is the type seen by overlays, draw functions, and interaction code — by the time
 *  those run, `color` is guaranteed to be set. Public consumers should write {@link Series}
 *  with color either supplied or omitted (chart picks one) and let the chart resolve it. */
export type ResolvedSeries<Meta = unknown> = Series<Meta> & { color: string }

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
    /** Which y-axis this series is scaled against. Defaults to {@link DEFAULT_Y_AXIS_ID}. */
    yAxisId?: string
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
    }
    /** Per-axis visibility flags. Each defaults to false (the series is included in everything). */
    visibility?: {
        /** Fully exclude the series — no rendering, no scale contribution, no tooltip, no hit-testing. */
        excluded?: boolean
        /** Render and participate in scales/hit-testing, but omit from tooltip seriesData. */
        fromTooltip?: boolean
        /** ValueLabels overlay skips this series. */
        fromValueLabels?: boolean
        /** Excluded from d3 stack computation (auxiliary overlays like trend lines / moving averages). */
        fromStack?: boolean
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
}

/** Context object passed to the `renderTooltip` render prop and tooltip event callbacks. */
export interface TooltipContext<Meta = unknown> {
    /** Index along the x-axis that the tooltip represents. */
    dataIndex: number
    /** The x-axis label at this index. */
    label: string
    /** One entry per visible series with its value and color at this index. */
    seriesData: { series: Series<Meta>; value: number; color: string }[]
    /** Pixel position (relative to the chart container) for anchoring the tooltip. */
    position: { x: number; y: number }
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

    // — Overlays —

    /** Show horizontal grid lines at y-axis tick positions. */
    showGrid?: boolean
    /** Tooltip behaviour. Defaults to enabled with no pinning and `follow-data` placement. */
    tooltip?: TooltipConfig
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** `vertical` (default): categories on x, values on y. `horizontal`: swapped. */
    axisOrientation?: 'vertical' | 'horizontal'
    /** True for BarChart `barLayout: 'percent'` / LineChart `percentStackView`. Surfaced
     *  on layout context so overlays can default to a percent formatter. */
    isPercent?: boolean
}

export interface TooltipConfig {
    /** Show a tooltip on hover. Defaults to true. Use the `tooltip` render prop on Chart to customize content. */
    enabled?: boolean
    /** When true, clicking a data point with multiple series pins the tooltip in place. */
    pinnable?: boolean
    /** Where the tooltip anchors vertically. `follow-data` (default) tracks the highest data point
     *  at the hovered x; `top` fixes the tooltip to the top of the chart so it doesn't jump
     *  vertically as the cursor moves between data points. */
    placement?: 'follow-data' | 'top'
}

export interface BarChartConfig extends ChartConfig {
    /** Defaults to `stacked`. */
    barLayout?: 'stacked' | 'grouped' | 'percent'
    /** Stacked bars only round the topmost segment. */
    barCornerRadius?: number
}

export interface LineChartConfig extends ChartConfig {
    percentStackView?: boolean
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
    /** Chart theme colors. */
    theme: ChartTheme
}

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

/** Generic scale interface that Chart uses for shared overlays and interaction. */
export interface ChartScales {
    /** Maps a label to an x pixel coordinate. */
    x: (label: string) => number | undefined
    /** Maps a y value to a pixel coordinate. Uses the default (left) axis. */
    y: (value: number) => number
    /** Returns tick values for the default (left) y-axis. */
    yTicks: () => number[]
    /** Per-axis y scales keyed by axis id. Present when dual axes are active.
     *  When absent, all series use `y` / `yTicks`. */
    yAxes?: Record<string, YAxisScale>
    /** Chart-type-private slot. Library code MUST NOT read this — it is populated by
     *  individual chart implementations (e.g. LineChart stashes raw d3 scales here so
     *  its `drawStatic` can use them) and is opaque to the base Chart and overlays.
     *  Typed as `unknown` so d3-style types don't leak through the public surface. */
    _private?: unknown
}
