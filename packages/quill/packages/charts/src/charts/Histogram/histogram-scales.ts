import { resolveCssColor } from '../../core/color-utils'
import { computeHistogramLayout } from '../../core/histogram-layout'
import type { HistogramEdges, HistogramLayout, HistogramScaleType } from '../../core/histogram-layout'
import type { ChartDimensions, ChartScales, ResolvedSeries } from '../../core/types'

interface HistogramChartPrivate {
    __histogram: HistogramLayout
    /** Canvas-ready series colors by series index, resolved once per layout rather than per frame. */
    __histogramColors: string[]
}

export function readHistogramLayout(scales: ChartScales): HistogramLayout | undefined {
    return (scales._private as HistogramChartPrivate | undefined)?.__histogram
}

export function readHistogramColors(scales: ChartScales): string[] {
    return (scales._private as HistogramChartPrivate | undefined)?.__histogramColors ?? []
}

export interface HistogramScalesInput {
    bins: HistogramEdges[]
    series: ResolvedSeries[]
    dimensions: ChartDimensions
    xScaleType?: HistogramScaleType
    yScaleType?: HistogramScaleType
    xTickFormatter?: (value: number) => string
    minBarHeight: number
}

/** Labels are prepared-bin indices, so `x(label)` is the center of the bin's column and
 *  `extent(label)` its width, which anchors the tooltip on the column's edge. */
export function createHistogramScales({ series, ...input }: HistogramScalesInput): ChartScales {
    const layout = computeHistogramLayout({
        ...input,
        series: series.map((s) => ({ data: s.data, excluded: s.visibility?.excluded })),
        pixelRatio: typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1,
    })
    const columnAt = (label: string): HistogramLayout['bins'][number] | undefined =>
        layout.bins[layout.columnOf[Number(label)] ?? -1]
    return {
        x: (label: string) => {
            const column = columnAt(label)
            return column ? (column.x0 + column.x1) / 2 : undefined
        },
        extent: (label: string) => {
            const column = columnAt(label)
            return column ? column.x1 - column.x0 : undefined
        },
        y: (value: number) => layout.yScale(value),
        yTicks: () => layout.yTicks,
        _private: {
            __histogram: layout,
            __histogramColors: series.map((s) => resolveCssColor(s.color)),
        } satisfies HistogramChartPrivate,
    }
}
