import * as d3 from 'd3'

import type { ChartDimensions, Series } from './types'
import { DEFAULT_Y_AXIS_ID } from './types'

type D3YScale = d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>

export interface ScaleSet {
    x: d3.ScalePoint<string>
    y: D3YScale
    /** Per-axis d3 scales keyed by axis id. Only populated when multiple axes are present. */
    yAxes?: Record<string, { scale: D3YScale; position: 'left' | 'right' }>
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
    } = {}
): d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number> {
    const { scaleType = 'linear', percentStack = false } = options

    if (percentStack) {
        return d3
            .scaleLinear()
            .domain([0, 1])
            .nice()
            .range([dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop])
    }

    const filteredSeries = series.filter((s) => !s.hidden)
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
        min = Math.max(min, 1e-10)
        max = Math.max(max, 1e-10)
        return d3
            .scaleLog()
            .domain([min, max])
            .nice()
            .range([dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop])
            .clamp(true)
    }

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
    } = {}
): ScaleSet {
    const x = createXScale(labels, dimensions)

    const axisIds = new Set(series.filter((s) => !s.hidden).map((s) => s.yAxisId ?? DEFAULT_Y_AXIS_ID))
    const hasMultipleAxes = axisIds.size > 1

    if (!hasMultipleAxes) {
        const y = createYScale(series, dimensions, {
            scaleType: options.scaleType,
            percentStack: options.percentStack,
        })
        return { x, y }
    }

    // DEFAULT_Y_AXIS_ID is always the left axis when present, regardless of series order.
    // Remaining axis ids keep their first-encountered order and take the right position.
    const orderedAxisIds = [
        ...(axisIds.has(DEFAULT_Y_AXIS_ID) ? [DEFAULT_Y_AXIS_ID] : []),
        ...Array.from(axisIds).filter((id) => id !== DEFAULT_Y_AXIS_ID),
    ]

    const yAxes: Record<string, { scale: D3YScale; position: 'left' | 'right' }> = {}
    orderedAxisIds.forEach((axisId, axisIndex) => {
        const axisSeries = series.filter((s) => !s.hidden && (s.yAxisId ?? DEFAULT_Y_AXIS_ID) === axisId)
        const scale = createYScale(axisSeries, dimensions, {
            scaleType: options.scaleType,
            percentStack: options.percentStack,
        })
        yAxes[axisId] = { scale, position: axisIndex === 0 ? 'left' : 'right' }
    })

    const primaryAxis = yAxes[DEFAULT_Y_AXIS_ID] ?? yAxes[orderedAxisIds[0]]

    return { x, y: primaryAxis.scale, yAxes }
}

export interface StackedBand {
    top: number[]
    bottom: number[]
}

function buildStackData(
    series: Series[],
    labels: string[],
    offset?: typeof d3.stackOffsetNone
): Map<string, StackedBand> {
    const visibleSeries = series.filter((s) => !s.hidden)
    if (visibleSeries.length === 0) {
        return new Map()
    }

    const tableData = labels.map((_, i) => {
        const row: Record<string, number> = {}
        for (const s of visibleSeries) {
            row[s.key] = Math.max(0, s.data[i] ?? 0)
        }
        return row
    })

    const stack = d3.stack<Record<string, number>>().keys(visibleSeries.map((s) => s.key))
    if (offset) {
        stack.offset(offset)
    }

    const stacked = stack(tableData)

    const result = new Map<string, StackedBand>()
    for (const layer of stacked) {
        result.set(layer.key, {
            top: layer.map((d) => d[1]),
            bottom: layer.map((d) => d[0]),
        })
    }
    return result
}

export function computeStackData(series: Series[], labels: string[]): Map<string, StackedBand> {
    return buildStackData(series, labels)
}

export function computePercentStackData(series: Series[], labels: string[]): Map<string, StackedBand> {
    return buildStackData(series, labels, d3.stackOffsetExpand)
}

export function autoFormatYTick(value: number, domainMax: number): string {
    if (domainMax < 2) {
        return value.toFixed(2)
    }
    if (domainMax < 5) {
        return value.toFixed(1)
    }
    return value.toLocaleString('en-US', { maximumFractionDigits: 0 })
}
