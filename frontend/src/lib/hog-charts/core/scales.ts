import * as d3 from 'd3'

import type { ChartDimensions, Series } from './types'

export interface ScaleSet {
    x: d3.ScalePoint<string>
    y: d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>
    /** Additional Y axes keyed by yAxisId */
    yAxes: Map<string, d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>>
}

export function createXScale(labels: string[], dimensions: ChartDimensions): d3.ScalePoint<string> {
    return d3
        .scalePoint<string>()
        .domain(labels)
        .range([dimensions.plotLeft, dimensions.plotLeft + dimensions.plotWidth])
        .padding(0)
}

export function createYScale(
    series: Series[],
    dimensions: ChartDimensions,
    options: {
        scaleType?: 'linear' | 'log'
        percentStack?: boolean
        yAxisId?: string
    } = {}
): d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number> {
    const { scaleType = 'linear', percentStack = false, yAxisId } = options

    if (percentStack) {
        return d3
            .scaleLinear()
            .domain([0, 1])
            .nice()
            .range([dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop])
    }

    const filteredSeries = series.filter(
        (s) => !s.hidden && (!yAxisId || s.yAxisId === yAxisId || (!s.yAxisId && yAxisId === 'y'))
    )
    const allValues = filteredSeries.flatMap((s) => s.data).filter((v) => v != null && isFinite(v))

    if (allValues.length === 0) {
        return d3
            .scaleLinear()
            .domain([0, 1])
            .range([dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop])
    }

    let min = d3.min(allValues) ?? 0
    let max = d3.max(allValues) ?? 1

    if (scaleType === 'log') {
        // Avoid log(0) by clamping minimum
        min = Math.max(min, 1e-10)
        max = Math.max(max, 1e-10)
        return d3
            .scaleLog()
            .domain([min, max])
            .nice()
            .range([dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop])
            .clamp(true)
    }

    // For linear scale, include 0 in domain if all values are positive
    if (min > 0) {
        min = 0
    }

    return d3
        .scaleLinear()
        .domain([min, max])
        .nice()
        .range([dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop])
}

export function createScales(
    series: Series[],
    labels: string[],
    dimensions: ChartDimensions,
    options: {
        scaleType?: 'linear' | 'log'
        percentStack?: boolean
        multipleYAxes?: boolean
    } = {}
): ScaleSet {
    const x = createXScale(labels, dimensions)

    // Collect unique yAxisIds
    const yAxisIds = new Set<string>()
    yAxisIds.add('y') // default axis
    for (const s of series) {
        if (s.yAxisId && !s.hidden) {
            yAxisIds.add(s.yAxisId)
        }
    }

    const yAxes = new Map<string, d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>>()

    if (options.multipleYAxes && yAxisIds.size > 1) {
        for (const axisId of yAxisIds) {
            yAxes.set(
                axisId,
                createYScale(series, dimensions, {
                    scaleType: options.scaleType,
                    percentStack: options.percentStack,
                    yAxisId: axisId,
                })
            )
        }
    }

    // Primary Y scale
    const y =
        options.multipleYAxes && yAxes.has('y')
            ? yAxes.get('y')!
            : createYScale(series, dimensions, {
                  scaleType: options.scaleType,
                  percentStack: options.percentStack,
              })

    return { x, y, yAxes }
}

/** Compute percent-stacked data using d3.stack */
export function computePercentStackData(series: Series[], labels: string[]): Map<string, number[]> {
    const visibleSeries = series.filter((s) => !s.hidden)
    if (visibleSeries.length === 0) {
        return new Map()
    }

    // Build tabular data for d3.stack
    const tableData = labels.map((_, i) => {
        const row: Record<string, number> = {}
        for (const s of visibleSeries) {
            row[s.key] = Math.max(0, s.data[i] ?? 0)
        }
        return row
    })

    const stack = d3
        .stack<Record<string, number>>()
        .keys(visibleSeries.map((s) => s.key))
        .offset(d3.stackOffsetExpand)

    const stacked = stack(tableData)

    const result = new Map<string, number[]>()
    for (const layer of stacked) {
        result.set(
            layer.key,
            layer.map((d) => d[1])
        )
    }
    return result
}

/** Auto-precision for Y tick formatting */
export function autoFormatYTick(value: number, domainMax: number): string {
    if (domainMax < 2) {
        return value.toFixed(2)
    }
    if (domainMax < 5) {
        return value.toFixed(1)
    }
    return value.toFixed(0)
}
