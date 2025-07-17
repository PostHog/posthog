import type {
    ActionsNode,
    EventsNode,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
} from '~/queries/schema/schema-general'
import { ExperimentDataWarehouseNode, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'

export type ExperimentVariantResult = ExperimentVariantResultFrequentist | ExperimentVariantResultBayesian

export const getMetricTag = (metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery): string => {
    if (metric.kind === NodeKind.ExperimentMetric) {
        return metric.metric_type.charAt(0).toUpperCase() + metric.metric_type.slice(1).toLowerCase()
    } else if (metric.kind === NodeKind.ExperimentFunnelsQuery) {
        return 'Funnel'
    }
    return 'Trend'
}

type MetricSource = EventsNode | ActionsNode | ExperimentDataWarehouseNode

const getDefaultName = (source: MetricSource): string | null | undefined => {
    switch (source.kind) {
        case NodeKind.EventsNode:
            return source.name || source.event
        case NodeKind.ActionsNode:
            return source.name || `Action ${source.id}`
        case NodeKind.ExperimentDataWarehouseNode:
            return source.table_name
    }
}

export const getDefaultMetricTitle = (metric: ExperimentMetric): string => {
    switch (metric.metric_type) {
        case ExperimentMetricType.MEAN:
            return getDefaultName(metric.source) || 'Untitled metric'
        case ExperimentMetricType.FUNNEL:
            return getDefaultName(metric.series[0]) || 'Untitled funnel'
    }
}

export function formatTickValue(value: number): string {
    if (value === 0) {
        return '0%'
    }

    // Determine number of decimal places needed
    const absValue = Math.abs(value)
    let decimals = 0

    if (absValue < 0.01) {
        decimals = 3
    } else if (absValue < 0.1) {
        decimals = 2
    } else if (absValue < 1) {
        decimals = 1
    } else {
        decimals = 0
    }

    return `${(value * 100).toFixed(decimals)}%`
}

/**
 * Converts a metric value to an X coordinate for chart rendering
 *
 * @param value The metric value to convert
 * @param chartBound The maximum absolute value in the chart (with padding)
 * @param viewBoxWidth The width of the SVG viewBox
 * @param horizontalPadding Padding to apply on both sides of the chart
 * @returns X coordinate in the SVG coordinate system
 */
export function valueToXCoordinate(
    value: number,
    chartRadius: number,
    viewBoxWidth: number,
    svgEdgeMargin: number = 20
): number {
    // Scale the value to fit within the padded area
    const percentage = (value / chartRadius + 1) / 2
    return svgEdgeMargin + percentage * (viewBoxWidth - 2 * svgEdgeMargin)
}

/**
 * Creates appropriately spaced tick values for experiment charts
 *
 * @param maxAbsValue The maximum absolute value to cover (typically the chart bound)
 * @param tickRangeFactor How much of the chart to cover (default 0.9 to not get to close to the edge of the chart)
 * @returns Array of nicely rounded tick values
 */
export function getNiceTickValues(maxAbsValue: number, tickRangeFactor: number = 0.9): number[] {
    // Round up maxAbsValue to ensure we cover all values
    maxAbsValue = Math.ceil(maxAbsValue * 10) / 10

    const magnitude = Math.floor(Math.log10(maxAbsValue))
    const power = Math.pow(10, magnitude)

    let baseUnit
    const normalizedMax = maxAbsValue / power
    if (normalizedMax <= 1) {
        baseUnit = 0.2 * power
    } else if (normalizedMax <= 2) {
        baseUnit = 0.5 * power
    } else if (normalizedMax <= 5) {
        baseUnit = 1 * power
    } else {
        baseUnit = 2 * power
    }

    const maxAllowedValue = maxAbsValue * tickRangeFactor
    const unitsNeeded = Math.ceil(maxAllowedValue / baseUnit)
    const decimalPlaces = Math.max(0, -magnitude + 1)

    const ticks: number[] = []
    for (let i = -unitsNeeded; i <= unitsNeeded; i++) {
        // Round each tick value to avoid floating point precision issues
        const tickValue = Number((baseUnit * i).toFixed(decimalPlaces))
        // Only include ticks within the allowed range
        if (Math.abs(tickValue) <= maxAllowedValue) {
            ticks.push(tickValue)
        }
    }
    return ticks
}

export function formatPValue(pValue: number | null | undefined): string {
    if (!pValue) {
        return 'N/A'
    }

    if (pValue < 0.001) {
        // Use scientific notation for very small p-values
        return '< 0.001'
    } else if (pValue < 0.01) {
        // Show 4 decimal places for small p-values
        return pValue.toFixed(4)
    }
    return pValue.toFixed(3)
}

export function formatChanceToWin(chanceToWin: number | null | undefined): string {
    if (chanceToWin == null) {
        return 'N/A'
    }

    // Convert to percentage and format
    const percentage = chanceToWin * 100

    if (percentage >= 99.9) {
        return '> 99.9%'
    } else if (percentage <= 0.1) {
        return '< 0.1%'
    } else if (percentage < 1) {
        return percentage.toFixed(2) + '%'
    }
    return percentage.toFixed(1) + '%'
}

export function isBayesianResult(result: ExperimentVariantResult): result is ExperimentVariantResultBayesian {
    return result.method === 'bayesian'
}

export function isFrequentistResult(result: ExperimentVariantResult): result is ExperimentVariantResultFrequentist {
    return result.method === 'frequentist'
}

export function getVariantInterval(result: ExperimentVariantResult): [number, number] | null {
    if (isBayesianResult(result)) {
        return result.credible_interval
    } else if (isFrequentistResult(result)) {
        return result.confidence_interval
    }
    return null
}

export function getIntervalLabel(result: ExperimentVariantResult): string {
    return isBayesianResult(result) ? 'Credible interval' : 'Confidence interval'
}

export interface PercentageChangeResult {
    text: string
    isSignificant: boolean
    isPositive: boolean | null
    pointEstimate: number | null
}

export function formatPercentageChange(result: ExperimentVariantResult): PercentageChangeResult {
    const interval = getVariantInterval(result)
    if (!interval) {
        return {
            text: '—',
            isSignificant: false,
            isPositive: null,
            pointEstimate: null,
        }
    }

    // Calculate the point estimate as the middle of the interval
    const [lower, upper] = interval
    const pointEstimate = (lower + upper) / 2
    const pointEstimatePercent = (pointEstimate * 100).toFixed(1)

    return {
        text: `${pointEstimatePercent}%`,
        isSignificant: result.significant,
        isPositive: pointEstimate > 0,
        pointEstimate,
    }
}
