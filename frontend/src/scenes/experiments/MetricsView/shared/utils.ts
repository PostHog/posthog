import type {
    ActionsNode,
    EventsNode,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentStatsBaseValidated,
    ExperimentTrendsQuery,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
} from '~/queries/schema/schema-general'
import {
    ExperimentDataWarehouseNode,
    ExperimentMetricType,
    NodeKind,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import { ExperimentMetricGoal } from '~/types'

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
        case ExperimentMetricType.RATIO:
            const numeratorName = getDefaultName(metric.numerator)
            const denominatorName = getDefaultName(metric.denominator)
            return `${numeratorName || 'Numerator'} / ${denominatorName || 'Denominator'}`
        default:
            return 'Untitled metric'
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
    axisRange: number,
    viewBoxWidth: number,
    svgEdgeMargin: number = 20
): number {
    // Scale the value to fit within the padded area
    const percentage = (value / axisRange + 1) / 2
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
        return '—'
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
        return '—'
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
        return result.credible_interval || null
    } else if (isFrequentistResult(result)) {
        return result.confidence_interval || null
    }
    return null
}

export function getIntervalLabel(result: ExperimentVariantResult): string {
    return isBayesianResult(result) ? 'Credible interval' : 'Confidence interval'
}

export function getIntervalBounds(result: ExperimentVariantResult): [number, number] {
    const interval = getVariantInterval(result)
    return interval ? [interval[0], interval[1]] : [0, 0]
}

export function formatIntervalPercent(result: ExperimentVariantResult): string {
    const interval = getVariantInterval(result)
    if (!interval) {
        return '—'
    }
    const [lower, upper] = interval
    return `[${(lower * 100).toFixed(2)}%, ${(upper * 100).toFixed(2)}%]`
}

export function getDelta(result: ExperimentVariantResult): number {
    const interval = getVariantInterval(result)
    if (!interval) {
        return 0
    }
    const [lower, upper] = interval
    return (lower + upper) / 2
}

export function getDeltaPercent(result: ExperimentVariantResult): number {
    return getDelta(result) * 100
}

export function isSignificant(result: ExperimentVariantResult): boolean {
    return result.significant || false
}

export function isDeltaPositive(result: ExperimentVariantResult): boolean | undefined {
    const interval = getVariantInterval(result)
    if (!interval) {
        return undefined
    }
    return getDelta(result) > 0
}

export function formatDeltaPercent(result: ExperimentVariantResult, decimals: number = 2): string {
    const interval = getVariantInterval(result)
    if (!interval) {
        return '—'
    }
    const deltaPercent = getDeltaPercent(result)
    const formatted = deltaPercent.toFixed(decimals)
    return `${deltaPercent > 0 ? '+' : ''}${formatted}%`
}

export function formatMetricValue(data: any, metric: ExperimentMetric): string {
    if (isExperimentRatioMetric(metric)) {
        // For ratio metrics, we need to calculate the ratio from sum and denominator_sum
        if (data.denominator_sum && data.denominator_sum > 0) {
            const ratio = data.sum / data.denominator_sum
            return ratio.toFixed(2)
        }
        return '0.000'
    }

    const primaryValue = data.sum / data.number_of_samples
    if (isNaN(primaryValue)) {
        return '—'
    }
    return isExperimentMeanMetric(metric) ? primaryValue.toFixed(2) : `${(primaryValue * 100).toFixed(2)}%`
}

export function getMetricSubtitleValues(
    variant: ExperimentStatsBaseValidated,
    metric: ExperimentMetric
): { numerator: number; denominator: number } {
    if (isExperimentRatioMetric(metric)) {
        return {
            numerator: variant.sum,
            denominator: variant.denominator_sum || 0,
        }
    }
    return {
        numerator: variant.sum,
        denominator: variant.number_of_samples || 0,
    }
}

export function isWinning(
    result: ExperimentVariantResult,
    goal: 'increase' | 'decrease' | undefined
): boolean | undefined {
    const deltaPositive = isDeltaPositive(result)
    if (deltaPositive === undefined) {
        return undefined
    }

    if (goal === 'decrease') {
        return !deltaPositive
    }
    return deltaPositive
}

export function getChanceToWin(
    result: ExperimentVariantResult,
    goal: 'increase' | 'decrease' | undefined
): number | undefined {
    if (!isBayesianResult(result)) {
        return undefined
    }
    const chanceToWin = result.chance_to_win
    if (chanceToWin == null) {
        return chanceToWin
    }
    // When goal is to decrease, invert chance to win because lower values are better
    if (goal === 'decrease') {
        return 1 - chanceToWin
    }
    return chanceToWin
}

export function formatChanceToWinForGoal(
    result: ExperimentVariantResult,
    goal: ExperimentMetricGoal | undefined
): string {
    const chanceToWin = getChanceToWin(result, goal)
    return formatChanceToWin(chanceToWin)
}

export interface MetricColors {
    positive: string
    negative: string
}

/**
 * Returns colors mapped according to the metric goal.
 * When goal is decrease, positive and negative colors are swapped.
 */
export function getMetricColors(
    colors: { BAR_POSITIVE: string; BAR_NEGATIVE: string },
    goal: ExperimentMetricGoal | undefined
): MetricColors {
    if (goal === 'decrease') {
        // Swap colors for decrease goal
        return {
            positive: colors.BAR_NEGATIVE,
            negative: colors.BAR_POSITIVE,
        }
    }
    return {
        positive: colors.BAR_POSITIVE,
        negative: colors.BAR_NEGATIVE,
    }
}
