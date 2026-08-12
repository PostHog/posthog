import type { ReactNode } from 'react'

import type {
    ChartLegendConfig,
    ChartMargins,
    ScatterMarkerShape,
    TooltipConfig,
    TooltipContext,
} from '../../core/types'

export type { ScatterMarkerShape }

export interface ScatterPoint<Meta = unknown> {
    x: number
    y: number
    /** Tooltip header. Falls back to the series label. */
    label?: string
    /** Falls back to the series' `pointRadius`. */
    radius?: number
    /** Falls back to the series color. */
    color?: string
    /** Arbitrary consumer data, handed back on hover and click. */
    meta?: Meta
}

export interface ScatterSeries<Meta = unknown> {
    /** Unique identifier: React key, legend identity, and the handle for hiding the series. */
    key: string
    /** Shown in the legend, and as the tooltip header for a point with no `label` of its own. */
    label: string
    points: ScatterPoint<Meta>[]
    /** Omit to take a palette color by series index. */
    color?: string
    /** Falls back to `config.pointRadius`. */
    pointRadius?: number
    /** Defaults to `circle`. */
    shape?: ScatterMarkerShape
}

export interface ScatterAxisConfig {
    /** Defaults to `linear`. A `log` axis drops points it can't place, i.e. non-positive ones. */
    scaleType?: 'linear' | 'log'
    /** Pins the domain instead of deriving it from the data. Pass a range back from `onAreaSelect`
     *  for drag-to-zoom, or share one domain across sibling charts. */
    domain?: readonly [number, number]
    /** Axis title. */
    label?: string
    /** Defaults to the shared auto-precision numeric formatter. */
    tickFormatter?: (value: number) => string
    /** Hides the tick labels and the title, and collapses the margin. */
    hide?: boolean
    /** Clamp a non-negative axis down to a zero baseline. Off by default, because forcing either of
     *  two independent measures to zero squashes the correlation into a corner. No-op on a log
     *  scale. */
    startAtZero?: boolean
}

export interface ScatterTooltipConfig<Meta = unknown> {
    /** Defaults to true. */
    enabled?: boolean
    /** Where the tooltip anchors. Same values as {@link TooltipConfig.placement}. */
    placement?: TooltipConfig['placement']
    /** Defaults to the point's `label`, or its series label. */
    labelFormatter?: (point: ScatterPointDatum<Meta>) => ReactNode
    /** Defaults to the x axis' tick formatter. */
    xFormatter?: (value: number, point: ScatterPointDatum<Meta>) => ReactNode
    /** Defaults to the y axis' tick formatter. */
    yFormatter?: (value: number, point: ScatterPointDatum<Meta>) => ReactNode
}

export interface ScatterChartConfig<Meta = unknown> {
    xAxis?: ScatterAxisConfig
    yAxis?: ScatterAxisConfig
    /** For series that don't set their own. Defaults to 3.5. */
    pointRadius?: number
    /** Marker fill opacity (0–1). Defaults to 0.7, so a dense cloud reads as denser rather than
     *  painting over itself. Markers keep an opaque outline either way. */
    fillOpacity?: number
    // Chrome toggles, named to match `ChartConfig` so a host's shared defaults spread over this
    // config too.
    showGrid?: boolean
    showAxisLines?: boolean
    showTickMarks?: boolean
    showCrosshair?: boolean
    /** Hidden by default. */
    legend?: ChartLegendConfig
    tooltip?: ScatterTooltipConfig<Meta>
    /** Applied over the computed margins. Should be referentially stable (a module-level constant). */
    margins?: Partial<ChartMargins>
}

/** A point as reported back to the consumer, plus its series and the color it was drawn in. */
export interface ScatterPointDatum<Meta = unknown> extends ScatterPoint<Meta> {
    seriesKey: string
    seriesLabel: string
    seriesIndex: number
    /** Index of this point within its own series' `points` array. */
    pointIndex: number
    /** Resolved through the series and palette fallbacks. */
    color: string
}

/** {@link TooltipContext} with the hovered point resolved, since the base context's `dataIndex`
 *  refers to the chart's internal flat index space. */
export interface ScatterTooltipContext<Meta = unknown> extends TooltipContext {
    point: ScatterPointDatum<Meta>
}

/** Bounds of a completed drag, in the points' own units. Feed back as an axis `domain` to zoom. */
export interface ScatterAreaSelection {
    x: [number, number]
    y: [number, number]
}
