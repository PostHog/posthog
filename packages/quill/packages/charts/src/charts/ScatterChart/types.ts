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
    /** Tooltip header for this point (e.g. the entity the row describes). Falls back to the
     *  series label. */
    label?: string
    /** Marker radius in px for this point alone — e.g. a cluster centroid drawn larger than its
     *  members. Falls back to the series' `pointRadius`. */
    radius?: number
    /** Marker color for this point alone. Falls back to the series color. */
    color?: string
    /** Arbitrary consumer data, handed back on hover and click. */
    meta?: Meta
}

export interface ScatterSeries<Meta = unknown> {
    /** Unique identifier — React key, legend identity, and the handle for hiding the series. */
    key: string
    /** Human-readable name shown in the legend and as a point's fallback tooltip header. */
    label: string
    points: ScatterPoint<Meta>[]
    /** CSS color for this series' markers. Omit to take a palette color by series index. */
    color?: string
    /** Marker radius in px. Falls back to `config.pointRadius`. */
    pointRadius?: number
    /** Marker glyph. Defaults to `circle`. */
    shape?: ScatterMarkerShape
}

/** Per-axis scale and formatting. Both axes are continuous, so neither takes category labels. */
export interface ScatterAxisConfig {
    /** `log` plots the axis logarithmically. Points with a non-positive coordinate on that axis
     *  can't be placed and are dropped from the chart. Defaults to `linear`. */
    scaleType?: 'linear' | 'log'
    /** Pin the axis domain instead of deriving it from the data — pass a range back from
     *  `onAreaSelect` to implement drag-to-zoom, or share one domain across sibling charts. */
    domain?: readonly [number, number]
    /** Axis title. */
    label?: string
    /** Format a tick value. Defaults to the shared auto-precision numeric formatter. */
    tickFormatter?: (value: number) => string
    /** Hide this axis' tick labels and title, and collapse its margin. */
    hide?: boolean
    /** Clamp a non-negative axis down to a zero baseline. Off by default — unlike a trend, a
     *  scatter's axes describe two independent measures, and forcing either to zero usually just
     *  squashes the correlation into a corner. Ignored on a log scale. */
    startAtZero?: boolean
}

export interface ScatterTooltipConfig<Meta = unknown> {
    /** Show a tooltip on hover. Defaults to true. */
    enabled?: boolean
    /** Where the tooltip anchors. Same values as {@link TooltipConfig.placement}; the app seam sets
     *  `cursor` for every chart, so pass this through rather than letting it drop. */
    placement?: TooltipConfig['placement']
    /** Format the header. Defaults to the point's `label`, or its series label. */
    labelFormatter?: (point: ScatterPointDatum<Meta>) => ReactNode
    /** Format the x readout. Defaults to the x axis' tick formatter. */
    xFormatter?: (value: number, point: ScatterPointDatum<Meta>) => ReactNode
    /** Format the y readout. Defaults to the y axis' tick formatter. */
    yFormatter?: (value: number, point: ScatterPointDatum<Meta>) => ReactNode
}

export interface ScatterChartConfig<Meta = unknown> {
    xAxis?: ScatterAxisConfig
    yAxis?: ScatterAxisConfig
    /** Marker radius in px for series that don't set their own. Defaults to 3.5. */
    pointRadius?: number
    /** Marker fill opacity (0–1). Defaults to 0.7, so overlapping points in a dense cloud read as
     *  denser rather than painting over each other. Markers keep an opaque outline either way. */
    fillOpacity?: number
    // Chrome toggles, all off by default and named to match `ChartConfig`, so a host can spread the
    // same defaults over this config as over every other chart's and get one house style.
    /** Draw grid lines at both axes' ticks. */
    showGrid?: boolean
    /** Draw the L-shaped axis baselines. */
    showAxisLines?: boolean
    /** Draw short tick marks outside the plot next to each axis label. */
    showTickMarks?: boolean
    /** Draw a vertical crosshair line through the hovered point. */
    showCrosshair?: boolean
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
    tooltip?: ScatterTooltipConfig<Meta>
    /** Per-side overrides applied on top of the computed chart margins. Should be referentially
     *  stable — pass a module-level constant rather than an inline object. */
    margins?: Partial<ChartMargins>
}

/** A point as reported back to the consumer: its own fields plus the series it came from and the
 *  color it was drawn in. */
export interface ScatterPointDatum<Meta = unknown> extends ScatterPoint<Meta> {
    seriesKey: string
    seriesLabel: string
    seriesIndex: number
    /** Index of this point within its own series' `points` array. */
    pointIndex: number
    /** The resolved marker color, after series and palette fallbacks. */
    color: string
}

/** {@link TooltipContext} with the hovered point resolved — a scatter point isn't addressable
 *  through the base context, whose `dataIndex` refers to the chart's internal flat index space. */
export interface ScatterTooltipContext<Meta = unknown> extends TooltipContext {
    point: ScatterPointDatum<Meta>
}

/** Data-space bounds of a completed drag selection, in the same units as the points. Feed them
 *  back as `config.xAxis.domain` / `config.yAxis.domain` to zoom. */
export interface ScatterAreaSelection {
    x: [number, number]
    y: [number, number]
}
