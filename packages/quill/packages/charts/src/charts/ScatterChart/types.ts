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
    radius?: number
    color?: string
    /** Arbitrary consumer data, handed back on hover and click. */
    meta?: Meta
}

export interface ScatterSeries<Meta = unknown> {
    /** React key, legend identity, and the handle for hiding the series. */
    key: string
    label: string
    points: ScatterPoint<Meta>[]
    /** Omit to take a palette color by series index. */
    color?: string
    pointRadius?: number
    shape?: ScatterMarkerShape
}

export interface ScatterAxisConfig {
    /** A `log` axis drops points it can't place, meaning non-positive ones. */
    scaleType?: 'linear' | 'log'
    /** Pins the domain instead of deriving it from the data. Pass a range back from `onAreaSelect`
     *  for drag-to-zoom, or share one domain across sibling charts. */
    domain?: readonly [number, number]
    /** Axis title. */
    label?: string
    tickFormatter?: (value: number) => string
    hide?: boolean
    /** Off by default, because forcing either of two independent measures to zero squashes the
     *  correlation into a corner. No-op on a log scale. */
    startAtZero?: boolean
}

export interface ScatterTooltipConfig<Meta = unknown> {
    enabled?: boolean
    placement?: TooltipConfig['placement']
    labelFormatter?: (point: ScatterPointDatum<Meta>) => ReactNode
    xFormatter?: (value: number, point: ScatterPointDatum<Meta>) => ReactNode
    yFormatter?: (value: number, point: ScatterPointDatum<Meta>) => ReactNode
}

export interface ScatterChartConfig<Meta = unknown> {
    xAxis?: ScatterAxisConfig
    yAxis?: ScatterAxisConfig
    pointRadius?: number
    /** Under 1 so a dense cloud reads as denser rather than painting over itself. Markers keep an
     *  opaque outline either way. */
    fillOpacity?: number
    showGrid?: boolean
    showAxisLines?: boolean
    showTickMarks?: boolean
    showCrosshair?: boolean
    /** Draws a dashed least-squares fit line per series, spanning that series' own points. Fitted in
     *  the axes' own space, so a log axis fits the log values. */
    showBestFit?: boolean
    legend?: ChartLegendConfig
    tooltip?: ScatterTooltipConfig<Meta>
    /** Applied over the computed margins. Should be referentially stable (a module-level constant). */
    margins?: Partial<ChartMargins>
}

export interface ScatterPointDatum<Meta = unknown> extends ScatterPoint<Meta> {
    seriesKey: string
    seriesLabel: string
    seriesIndex: number
    /** Index of this point within its own series' `points` array. */
    pointIndex: number
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
