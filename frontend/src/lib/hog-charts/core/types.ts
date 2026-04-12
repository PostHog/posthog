import type { AxisFormat, ChartTheme } from 'lib/charts/types'
export type { AxisFormat, ChartTheme }

export interface Series<Meta = unknown> {
    /** Unique identifier used to key React elements and look up stacked data. */
    key: string
    /** Human-readable name shown in tooltips and legends. */
    label: string
    /** Numeric values for each x-axis label. Must be the same length as the labels array. */
    data: number[]
    /** CSS color string (hex, rgb, etc.) for the line and associated fill/points. */
    color: string
    /** When true, fills the area between the line and the x-axis baseline. */
    fillArea?: boolean
    /** Opacity of the area fill. Range 0–1, defaults to 0.5. Ignored when `fillArea` is false. */
    fillOpacity?: number
    /** Canvas line dash pattern, e.g. [10, 10] for evenly dashed. Omit or [] for solid. */
    dashPattern?: number[]
    /** Index from which the line becomes dashed (inclusive). Clamped to data bounds. */
    dashedFromIndex?: number
    /** Index up to which the line is dashed (inclusive). Clamped to data bounds. */
    dashedToIndex?: number
    /** Dash pattern for the `dashedFromIndex`/`dashedToIndex` portions. Defaults to [10, 10]. */
    dashedPattern?: number[]
    /** When true, the series is excluded from rendering, scales, and tooltips. */
    hidden?: boolean
    /** When true, the series still renders and participates in scales and hit-testing,
     *  but is omitted from the tooltip's seriesData so it doesn't appear as a row. */
    hideFromTooltip?: boolean
    /** Radius in px for data point dots. Set to 0 or omit to hide dots. */
    pointRadius?: number
    /** Arbitrary consumer data attached to this series. Flows through to TooltipContext
     *  so custom tooltip components can access domain-specific information (e.g. breakdown
     *  values, comparison labels, anomaly scores) without the library needing to know about them.
     *  Defaults to `unknown` so the library is meta-agnostic internally; adapters narrow it
     *  via `Series<MyMeta>` to get typed reads in their tooltip/click handlers. */
    meta?: Meta
}

/** Data passed to the `onPointClick` callback when a user clicks a data point. */
export interface PointClickData<Meta = unknown> {
    /** Index of the clicked series within the original series array. */
    seriesIndex: number
    /** Index along the x-axis (into the labels array) that was clicked. */
    dataIndex: number
    /** The series that was clicked. */
    series: Series<Meta>
    /** The y-value at the clicked point. */
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
    /** Show a tooltip on hover. Defaults to true. Use the `tooltip` prop to customize content. */
    showTooltip?: boolean
    /** When true, clicking a data point with multiple series pins the tooltip in place. */
    pinnableTooltip?: boolean
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
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
    series: Series[]
    /** X-axis labels. */
    labels: string[]
    /** Index of the currently hovered data point, or -1. */
    hoverIndex: number
    /** Chart theme colors. */
    theme: ChartTheme
}

/** Resolves the y-value for a series at a given data index. Used by interaction/tooltip layer. */
export type ResolveValueFn = (series: Series, dataIndex: number) => number

/** Factory function that chart types provide to create their scales from dimensions and data. */
export type CreateScalesFn = (series: Series[], labels: string[], dimensions: ChartDimensions) => ChartScales

/** Generic scale interface that Chart uses for shared overlays and interaction. */
export interface ChartScales {
    /** Maps a label to an x pixel coordinate. */
    x: (label: string) => number | undefined
    /** Maps a y value to a pixel coordinate. */
    y: (value: number) => number
    /** Returns tick values for the y-axis. */
    yTicks: () => number[]
}
