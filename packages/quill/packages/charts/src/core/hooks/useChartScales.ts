import { useMemo } from 'react'

import type { ChartDimensions, ChartMargins, ChartScales, CreateScalesFn, ResolvedSeries } from '../types'
import { computeYAxisGutters, type Gutter, widenToFitGutters } from '../y-axis-gutters'
import { useResolvedYFormatter } from './useResolvedYFormatters'

type YTickFormatter = (value: number) => string

interface UseChartScalesOptions {
    canvasDimensions: ChartDimensions | null
    series: ResolvedSeries[]
    labels: string[]
    createScales: CreateScalesFn
    showYGutters: boolean
    yTickFormatter?: YTickFormatter
    yAxisFormatters?: Record<string, YTickFormatter>
    yAxisTitles?: Record<string, string>
    yAxisHidden?: Record<string, boolean>
    marginsOverride?: Partial<ChartMargins>
}

interface UseChartScalesResult {
    dimensions: ChartDimensions | null
    scales: ChartScales | null
    yGutters: Gutter[]
    resolvedYFormatter: YTickFormatter
}

/** Builds the scales, then widens the plot when the y-axis labels they draw overflow the margin estimate. */
export function useChartScales({
    canvasDimensions,
    series,
    labels,
    createScales,
    showYGutters,
    yTickFormatter,
    yAxisFormatters,
    yAxisTitles,
    yAxisHidden,
    marginsOverride,
}: UseChartScalesOptions): UseChartScalesResult {
    const firstScales = useMemo(
        () => (canvasDimensions ? createScales(series, labels, canvasDimensions) : null),
        [canvasDimensions, createScales, series, labels]
    )
    const resolvedYFormatter = useResolvedYFormatter(firstScales, yTickFormatter)
    const fixedLeft = marginsOverride?.left
    const fixedRight = marginsOverride?.right

    return useMemo(() => {
        if (!canvasDimensions || !firstScales) {
            return { dimensions: canvasDimensions, scales: firstScales, yGutters: [], resolvedYFormatter }
        }
        const guttersFor = (scales: ChartScales): Gutter[] =>
            showYGutters
                ? computeYAxisGutters(scales, {
                      yTicks: scales.yTicks(),
                      yTickFormatter: resolvedYFormatter,
                      userYTickFormatter: yTickFormatter,
                      yAxisFormatters,
                      titles: yAxisTitles,
                      hiddenAxes: yAxisHidden,
                  })
                : []
        const firstGutters = guttersFor(firstScales)
        const dimensions = widenToFitGutters(canvasDimensions, firstGutters, { left: fixedLeft, right: fixedRight })
        if (dimensions === canvasDimensions) {
            return { dimensions, scales: firstScales, yGutters: firstGutters, resolvedYFormatter }
        }
        const scales = createScales(series, labels, dimensions)
        return { dimensions, scales, yGutters: guttersFor(scales), resolvedYFormatter }
    }, [
        canvasDimensions,
        firstScales,
        createScales,
        series,
        labels,
        showYGutters,
        resolvedYFormatter,
        yTickFormatter,
        yAxisFormatters,
        yAxisTitles,
        yAxisHidden,
        fixedLeft,
        fixedRight,
    ])
}
