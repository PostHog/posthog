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

/** A labeled vertical line. A `percentile` marker estimates its value from the bins, interpolating
 *  linearly inside the bin that crosses it; a `value` marker sits at an exact x value, such as a
 *  percentile computed upstream or an SLO threshold. */
export type HistogramMarker =
    | {
          /** 0 to 100. Labeled `p50`, `p95` and so on unless `label` is set. */
          percentile: number
          value?: never
          label?: string
          /** CSS color. Defaults to the axis label color. */
          color?: string
      }
    | {
          value: number
          percentile?: never
          label: string
          /** CSS color. Defaults to the axis label color. */
          color?: string
      }

export interface HistogramAxisConfig extends YFormatterConfig, Pick<YAxisConfig, 'label' | 'tickFormatter' | 'hide'> {
    /** Defaults to `linear`. On the x axis `log` suits latency, where bins grow geometrically: a bin
     *  starting at or below zero is drawn one bin-ratio wide, and a bin ending at or below zero is not
     *  drawn but still counts toward totals. On the y axis `log` keeps a long tail readable. */
    scale?: YAxisConfig['scale']
}

export interface HistogramTooltipConfig {
    /** Defaults to true. */
    enabled?: boolean
    /** Defaults to `cursor`. */
    placement?: TooltipConfig['placement']
}

export interface HistogramConfig {
    /** Bin-edge axis. Its formatter also writes the tooltip's bin range and the marker values. */
    xAxis?: HistogramAxisConfig
    /** Count axis. A `log` scale keeps a long tail readable next to one tall bin. */
    yAxis?: HistogramAxisConfig
    /** Labeled vertical lines, such as `[{ percentile: 50 }, { percentile: 99 }]`. */
    markers?: HistogramMarker[]
    /** Defaults to true. */
    showGrid?: boolean
    /** Defaults to true. */
    showAxisLines?: boolean
    /** Defaults to true. */
    showTickMarks?: boolean
    /** Floor (px) on the height of a non-empty bin, so a few samples next to a tall bin still show.
     *  Empty bins never draw. Defaults to 1. */
    minBarHeight?: number
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
