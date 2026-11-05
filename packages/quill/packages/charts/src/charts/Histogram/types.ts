import type { ChartLegendConfig, ChartMargins, TooltipConfig, TooltipContext } from '../../core/types'
import type { YAxisConfig } from '../../utils/use-axis-formatters'
import type { YFormatterConfig } from '../../utils/y-formatters'

export interface HistogramBin<Meta = unknown> {
    /** Lower edge, inclusive, in x-axis units (for example nanoseconds). */
    start: number
    /** Upper edge, exclusive. Must be greater than `start`. */
    end: number
    /** Samples in the bin. Ignored when the chart has `series`. */
    count?: number
    /** Arbitrary consumer data, handed back in the tooltip context. */
    meta?: Meta
}

/** One stacked layer, such as ok or error requests. */
export interface HistogramSeries {
    /** React key, legend identity, and stacking order (first series sits at the bottom). */
    key: string
    /** Name shown in the legend and the tooltip. */
    label: string
    /** Count per bin, aligned with the chart's `bins` array as passed (before any sorting). */
    data: number[]
    /** Omit to take a palette color by series index. Accepts `var(--…)`. */
    color?: string
}

/** A value range on the x axis. `min` is inclusive and `max` is exclusive, matching bin edges. */
export interface HistogramRange {
    min: number
    max: number
}

export type HistogramAxisConfig = YFormatterConfig & Pick<YAxisConfig, 'label' | 'tickFormatter' | 'hide'>

export interface HistogramXAxisConfig extends HistogramAxisConfig {
    /** Defaults to `linear`. `log` suits latency, where bins grow geometrically: a bin starting at or
     *  below zero is drawn one bin-ratio wide, and a bin ending at or below zero is not drawn but
     *  still counts toward totals. */
    scale?: YAxisConfig['scale']
}

/** `placement` defaults to `cursor`. */
export type HistogramTooltipConfig = Pick<TooltipConfig, 'enabled' | 'placement'>

export interface HistogramConfig {
    /** Bin-edge axis. Its formatter also writes the tooltip's bin range. */
    xAxis?: HistogramXAxisConfig
    /** Count axis. */
    yAxis?: HistogramAxisConfig
    /** Defaults to true. */
    showGrid?: boolean
    /** Defaults to true. */
    showAxisLines?: boolean
    /** Defaults to true. */
    showTickMarks?: boolean
    /** Built-in legend for stacked `series`. Hidden by default. */
    legend?: ChartLegendConfig
    tooltip?: HistogramTooltipConfig
    /** Applied over the computed margins. Should be referentially stable (a module-level constant). */
    margins?: Partial<ChartMargins>
}

/** {@link TooltipContext} with the hovered bin resolved. `seriesData` holds one row per visible
 *  series. */
export interface HistogramTooltipContext<Meta = unknown> extends TooltipContext {
    /** The hovered bin, with the edges as drawn (an overlapping bin starts where the previous one
     *  ends). When several bins share one pixel column, a bin spanning them all with their summed
     *  count and no `meta`. */
    bin: HistogramBin<Meta>
    /** The bins in the hovered column, as passed. Usually one. */
    bins: HistogramBin<Meta>[]
    /** Samples in the bin across visible series. */
    count: number
    /** `count` as a share (0 to 1) of every visible sample. */
    fraction: number
    /** Share (0 to 1) of visible samples below the bin's `end`. */
    cumulativeFraction: number
}
